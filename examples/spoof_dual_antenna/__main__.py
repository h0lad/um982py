"""Compare dual-antenna heading, sky view and spoof indicators."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from examples._console_capture import open_receiver
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
from um982py import Receiver
from um982py.capture import iter_frames
from um982py.commands import Log
from um982py.errors import ResponseTimeout
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


def _query_capture(receiver: Receiver) -> Capture:
    collected: dict[str, tuple[Record, ...]] = {}
    for field, log in _FIELDS.items():
        print(f"Querying {log.value}...", file=sys.stderr, flush=True)
        try:
            collected[field] = receiver.collect(log.read(binary=False))
        except ResponseTimeout:
            collected[field] = ()
    collected["sky"] = (*collected["sky"], *_collect_binary_sky(receiver))
    return Capture(
        enu=collected["enu"],
        ecef=collected["ecef"],
        position=collected["position"],
        offset=collected["offset"],
        spoof=collected["spoof"],
        sky=collected["sky"],
    )


def _collect_binary_sky(receiver: Receiver) -> tuple[Record, ...]:
    try:
        return receiver.collect(Log.SATVIS2.read(binary=True))
    except ResponseTimeout:
        return ()


def _enu_baseline(capture: Capture, *, swapped: bool) -> EnuBaseline | None:
    """Last ENU baseline with the antenna roles applied."""
    if not capture.enu:
        return None
    baseline = EnuBaseline.from_record(capture.enu[-1])
    return baseline.negated() if swapped else baseline


def _heading_agreement(
    capture: Capture, *, swapped: bool = False
) -> HeadingAgreement | None:
    """Heading agreement, or ``None`` when a required record is missing."""
    if not (capture.enu and capture.ecef and capture.position):
        return None
    position = capture.position[-1]
    ecef = EcefBaseline.from_record(capture.ecef[-1])
    reference = (ecef.negated() if swapped else ecef).to_enu(
        position.real("lat"), position.real("lon")
    )
    enu = _enu_baseline(capture, swapped=swapped)
    if enu is None:
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


def _payload(capture: Capture, *, swapped: bool = False) -> dict[str, object]:
    heading = _heading_agreement(capture, swapped=swapped)
    skies = _compare_latest_sky_snapshots(capture)
    spoof = _latest_spoof_status(capture)
    return {
        "status": "checks_available"
        if heading is not None and spoof is not None
        else "incomplete_checks",
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
    args = parser.parse_args(argv)
    debug_header(args, "spoof_dual_antenna")
    if args.replay is not None:
        capture = _capture_from_transcripts([Path(args.replay)])
    elif args.transcripts is not None:
        capture = _capture_from_transcripts(
            sorted(Path(args.transcripts).glob("*.bin"))
        )
    else:
        receiver = open_receiver(args)
        try:
            capture = _query_capture(receiver)
        finally:
            receiver.close()
    payload = _payload(capture, swapped=args.swap_antennas)
    alarms = payload["alarms"]
    print(
        f"Spoof checks: status={payload['status']}, "
        f"{len(alarms) if isinstance(alarms, list) else 0} alarms",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
