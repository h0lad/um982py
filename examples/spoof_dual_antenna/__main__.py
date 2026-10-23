"""Runs the dual-antenna spoofing checks from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from examples.spoof_dual_antenna import (
    Alarm,
    EcefBaseline,
    EnuBaseline,
    HeadingAgreement,
    HeadingOffset,
    SkyComparison,
    SpoofStatus,
    alarms,
    apply_heading_offset,
    compare_headings,
    compare_snapshots,
    sky_snapshots,
)
from um982py import Receiver
from um982py.capture import open_receiver, read_frames
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout
from um982py.experimental import FirmwareLog
from um982py.messages import Record


@dataclass(frozen=True, slots=True)
class Capture:
    """Decoded records of every log the spoofing check consumes."""

    enu: tuple[Record, ...] = ()
    ecef: tuple[Record, ...] = ()
    position: tuple[Record, ...] = ()
    offset: tuple[Record, ...] = ()
    spoof: tuple[Record, ...] = ()
    sky: tuple[Record, ...] = ()


def _records(paths: Sequence[Path], log: FirmwareLog) -> tuple[Record, ...]:
    """Decode one log from every captured transcript given."""
    decoded = []
    for path in paths:
        for message in read_frames(path):
            for binary in (True, False):
                if log.request(binary=binary).matches(message):
                    decoded.append(log.decode(message))
                    break
    return tuple(decoded)


def _captured(paths: Sequence[Path]) -> Capture:
    """Decode the single-value logs and the sky views from transcripts."""
    return Capture(
        enu=_records(paths, FirmwareLog.BSLNENUHD),
        ecef=_records(paths, FirmwareLog.BSLNXYZHD),
        position=_records(paths, FirmwareLog.BESTPOS),
        offset=_records(paths, FirmwareLog.HEADINGOFFSET),
        spoof=_records(paths, FirmwareLog.SPOOFINFO),
        sky=_records(paths, FirmwareLog.SATVIS2),
    )


_FIELDS: dict[str, FirmwareLog] = {
    "enu": FirmwareLog.BSLNENUHD,
    "ecef": FirmwareLog.BSLNXYZHD,
    "position": FirmwareLog.BESTPOS,
    "offset": FirmwareLog.HEADINGOFFSET,
    "spoof": FirmwareLog.SPOOFINFO,
    "sky": FirmwareLog.SATVIS2,
}


def _queried(receiver: Receiver) -> Capture:
    """Query every log once, taking the sky view from two consecutive frames."""
    collected: dict[str, tuple[Record, ...]] = {}
    for field, log in _FIELDS.items():
        print(f"Querying {log.value}...", file=sys.stderr, flush=True)
        try:
            collected[field] = receiver.collect(log.read(binary=False))
        except ResponseTimeout:
            collected[field] = ()
    collected["sky"] = (*collected["sky"], *_sky_again(receiver))
    return Capture(
        enu=collected["enu"],
        ecef=collected["ecef"],
        position=collected["position"],
        offset=collected["offset"],
        spoof=collected["spoof"],
        sky=collected["sky"],
    )


def _sky_again(receiver: Receiver) -> tuple[Record, ...]:
    """Collect the second SATVIS2 view, which the binary form provides."""
    try:
        return receiver.collect(FirmwareLog.SATVIS2.read(binary=True))
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


def _sky_pairs(capture: Capture) -> tuple[SkyComparison, ...]:
    """Compare the two most recent SATVIS2 snapshots constellation by constellation."""
    snapshots = sky_snapshots(capture.sky)
    if len(snapshots) < 2:
        return ()
    return compare_snapshots(snapshots[-2], snapshots[-1])


def _spoof_status(capture: Capture) -> SpoofStatus | None:
    """Spoofing indicator of the last SPOOFINFO record."""
    return None if not capture.spoof else SpoofStatus.from_record(capture.spoof[-1])


def _payload(capture: Capture, *, swapped: bool = False) -> dict[str, object]:
    """Report of the heading, sky-view and spoof-indicator checks."""
    heading = _heading_agreement(capture, swapped=swapped)
    skies = _sky_pairs(capture)
    spoof = _spoof_status(capture)
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
        "alarms": [alarm.value for alarm in _alarms(heading, skies, spoof)],
    }


def _alarms(
    heading: HeadingAgreement | None,
    skies: Sequence[SkyComparison],
    spoof: SpoofStatus | None,
) -> tuple[Alarm, ...]:
    """Alarms over whichever checks the capture allowed."""
    return alarms(heading, skies, spoof)


def _heading_payload(agreement: HeadingAgreement | None) -> dict[str, object] | None:
    """Serialise one heading agreement."""
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
    """Serialise one sky comparison."""
    return {
        "shared": len(comparison.shared),
        "absent": list(comparison.absent),
        "max_elevation_difference": _maximum(
            [item.elevation_difference for item in comparison.disagreements]
        ),
        "max_azimuth_difference": _maximum(
            [item.azimuth_difference for item in comparison.disagreements]
        ),
        "consistent": comparison.consistent,
    }


def _maximum(values: Sequence[float]) -> float | None:
    """Largest absolute value, or ``None`` when the sequence is empty."""
    return max((abs(value) for value in values), default=None)


def _spoof_payload(spoof: SpoofStatus | None) -> dict[str, object] | None:
    """Serialise the SPOOFINFO status."""
    if spoof is None:
        return None
    return {
        "position_type": spoof.position_type,
        "indicator": spoof.indicator,
        "spoofed": spoof.spoofed,
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
        capture = _captured([Path(args.replay)])
    elif args.transcripts is not None:
        capture = _captured(sorted(Path(args.transcripts).glob("*.bin")))
    else:
        receiver = open_receiver(args)
        try:
            capture = _queried(receiver)
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
