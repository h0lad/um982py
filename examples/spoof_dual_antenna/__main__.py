# Compare dual-antenna heading, sky view and spoof indicators.

import argparse
import sys
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from examples._console_capture import capture_records, open_receiver
from examples.spoof_dual_antenna import (
    EcefBaseline,
    EnuBaseline,
    HeadingAgreement,
    HeadingOffset,
    SkyComparison,
    alarms,
    apply_heading_offset,
    compare_headings,
    compare_snapshots,
    sky_snapshots,
)
from um982py.capture import iter_frames, select_position
from um982py.commands import Log
from um982py.errors import ResponseTimeout
from um982py.geodesy import geodetic_from_ecef, receiver_ecef
from um982py.measurement import gps_epoch
from um982py.messages import Record, SpoofInfo


@dataclass(frozen=True, slots=True)
class Capture:
    """Decoded records of every log the spoofing check consumes."""

    enu: tuple[Record, ...] = ()
    ecef: tuple[Record, ...] = ()
    position: tuple[Record, ...] = ()
    offset: tuple[Record, ...] = ()
    spoof: tuple[Record, ...] = ()
    sky: tuple[Record, ...] = ()


def _decode_captured_records(paths: Sequence[Path], log: Log) -> tuple[Record, ...]:
    decoded = []
    for path in paths:
        for message in iter_frames(path):
            for binary in (True, False):
                if log.request(binary=binary).matches(message):
                    decoded.append(log.decode(message))
                    break
    return tuple(decoded)


def _capture_from_transcripts(paths: Sequence[Path]) -> Capture:
    return Capture(
        enu=_decode_captured_records(paths, Log.BSLNENUHD),
        ecef=_decode_captured_records(paths, Log.BSLNXYZHD),
        position=_decode_captured_records(paths, Log.BESTPOS),
        offset=_decode_captured_records(paths, Log.HEADINGOFFSET),
        spoof=_decode_captured_records(paths, Log.SPOOFINFO),
        sky=_decode_captured_records(paths, Log.SATVIS2),
    )


_FIELDS: dict[str, Log] = {
    "enu": Log.BSLNENUHD,
    "ecef": Log.BSLNXYZHD,
    "position": Log.BESTPOS,
    "offset": Log.HEADINGOFFSET,
    "spoof": Log.SPOOFINFO,
    "sky": Log.SATVIS2,
}


def _enu_baseline(capture: Capture, *, swapped: bool) -> EnuBaseline | None:
    """Last ENU baseline with the antenna roles applied."""
    if not capture.enu:
        return None
    baseline = EnuBaseline.from_record(capture.enu[-1])
    return baseline.negated() if swapped else baseline


def _heading_agreement(
    capture: Capture, *, swapped: bool = False, tolerance: float = 1.0
) -> HeadingAgreement | None:
    """Heading agreement, or ``None`` when a required record is missing."""
    if not (capture.enu and capture.ecef and capture.position):
        return None
    try:
        valid_enu = [
            row for row in capture.enu if row.get("p_sol_status") in (0, "SOL_COMPUTED")
        ]
        valid_ecef = [
            row
            for row in capture.ecef
            if row.get("p_sol_status") in (0, "SOL_COMPUTED")
        ]
        if not valid_enu or not valid_ecef:
            return None
        enu_record = max(valid_enu, key=gps_epoch)
        epoch = gps_epoch(enu_record)
        ecef_record = min(valid_ecef, key=lambda row: abs(gps_epoch(row) - epoch))
        if abs(gps_epoch(ecef_record) - epoch) > tolerance:
            return None
        position = select_position(capture.position, epoch, tolerance)
        latitude, longitude, _ = geodetic_from_ecef(*receiver_ecef(position))
        ecef = EcefBaseline.from_record(ecef_record)
        reference = (ecef.negated() if swapped else ecef).to_enu(latitude, longitude)
        enu = EnuBaseline.from_record(enu_record)
        if swapped:
            enu = enu.negated()
    except KeyError, TypeError, ValueError:
        return None
    return compare_headings(enu, reference)


def _offset_payload(
    capture: Capture, *, swapped: bool = False
) -> dict[str, object] | None:
    """Mount offset and the heading the receiver reports after applying it."""
    if not capture.offset:
        return None
    offset = HeadingOffset.from_record(capture.offset[-1])
    payload: dict[str, object] = {"heading": offset.heading, "pitch": offset.pitch}
    enu = _enu_baseline(capture, swapped=swapped)
    if enu is not None:
        reported = apply_heading_offset(enu, offset)
        payload["reported_heading"] = reported.heading
    return payload


def _compare_latest_sky_snapshots(capture: Capture) -> tuple[SkyComparison, ...]:
    snapshots = sky_snapshots(capture.sky)
    if len(snapshots) < 2:
        return ()
    return compare_snapshots(snapshots[-2], snapshots[-1])


def _latest_spoof_status(capture: Capture) -> SpoofInfo | None:
    return None if not capture.spoof else SpoofInfo.from_record(capture.spoof[-1])


def _payload(
    capture: Capture, *, swapped: bool = False, tolerance: float = 1.0
) -> dict[str, object]:
    heading = _heading_agreement(capture, swapped=swapped, tolerance=tolerance)
    skies = _compare_latest_sky_snapshots(capture)
    spoof = _latest_spoof_status(capture)
    return {
        "status": "checks_available"
        if heading is not None and spoof is not None and skies
        else "incomplete_checks",
        "available_checks": {
            "heading": heading is not None,
            "sky": bool(skies),
            "spoof_indicator": spoof is not None,
        },
        "heading_epoch_tolerance_s": tolerance,
        "heading": _heading_payload(heading),
        "sky_scope": "successive SATVIS2 snapshots, not separate antenna feeds",
        "offset": _offset_payload(capture, swapped=swapped),
        "antenna_roles": "swapped" if swapped else "documented",
        "sky": [_sky_payload(comparison) for comparison in skies],
        "spoof": _spoof_payload(spoof),
        "alarms": [alarm.value for alarm in alarms(heading, skies, spoof)],
    }


def _heading_payload(agreement: HeadingAgreement | None) -> dict[str, object] | None:
    if agreement is None:
        return None
    return {
        "heading": agreement.heading,
        "reference": agreement.reference,
        "difference": agreement.difference,
        "sigma": agreement.sigma,
        "tolerance": agreement.tolerance,
        "resolvable": agreement.resolvable,
        "consistent": agreement.consistent,
    }


def _sky_payload(comparison: SkyComparison) -> dict[str, object]:
    return {
        "shared": len(comparison.shared),
        "absent": list(comparison.absent),
        "max_elevation_difference": _max_absolute(
            [item.elevation_difference for item in comparison.disagreements]
        ),
        "max_azimuth_difference": _max_absolute(
            [item.azimuth_difference for item in comparison.disagreements]
        ),
        "consistent": comparison.consistent,
    }


def _max_absolute(values: Sequence[float]) -> float | None:
    return max((abs(value) for value in values), default=None)


def _spoof_payload(spoof: SpoofInfo | None) -> dict[str, object] | None:
    if spoof is None:
        return None
    return {
        "position_type": spoof.position_type_label,
        "indicator": spoof.indicator,
        "spoofed": spoof.is_suspect,
        "notice_mask": int(spoof.notices),
        "time_notice_mask": int(spoof.time_notices),
        "signal_mask": int(spoof.signals),
        "gps_satellites": list(spoof.gps_satellites),
        "bds_satellites": list(spoof.bds_satellites),
        "galileo_satellites": list(spoof.galileo_satellites),
        "glonass_satellites": list(spoof.glonass_satellites),
    }


def _heading_offset(args: argparse.Namespace) -> tuple[Record, ...]:
    """Query the configured heading offset once in its ASCII form."""
    receiver = open_receiver(args)
    try:
        return tuple(receiver.collect(Log.HEADINGOFFSET.read(binary=False)))
    except ResponseTimeout:
        return ()
    finally:
        receiver.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Replay transcripts or query the receiver, then report the spoofing checks."""
    parser = ExampleParser(
        prog="python -m examples.spoof_dual_antenna", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--transcripts",
        type=Path,
        default=None,
        help="directory of captured transcripts to replay",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_output_interval(default=1.0)
    parser.add_argument(
        "--position-tolerance",
        type=float,
        default=1.0,
        help="maximum heading baseline/position epoch offset in seconds",
    )
    args = parser.parse_args(argv)
    debug_header(args, "spoof_dual_antenna")
    if args.replay is not None:
        capture = _capture_from_transcripts([Path(args.replay)])
    elif args.transcripts is not None:
        capture = _capture_from_transcripts(
            sorted(Path(args.transcripts).glob("*.bin"))
        )
    else:
        # Both baseline representations use the physical ANT1 local origin.
        capture_args = copy(args)
        capture_args.antenna = "primary"
        capture_args.swap_antennas = False
        # HEADINGOFFSET only has verified one-shot queries, so it is read once
        # after the periodic logs instead of being subscribed with them.
        periodic = {field: log for field, log in _FIELDS.items() if field != "offset"}
        captured = capture_records(
            capture_args,
            list(periodic.values()),
            duration=args.duration,
            interval=args.interval,
        )
        capture = Capture(
            **{field: captured[log.value] for field, log in periodic.items()},
            offset=_heading_offset(capture_args),
        )
    payload = _payload(
        capture, swapped=args.swap_antennas, tolerance=args.position_tolerance
    )
    alarms = payload["alarms"]
    print(
        f"Spoof checks: status={payload['status']}, "
        f"{len(alarms) if isinstance(alarms, list) else 0} alarms",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 1 if payload["status"] == "incomplete_checks" else 0


if __name__ == "__main__":
    raise SystemExit(run(main))
