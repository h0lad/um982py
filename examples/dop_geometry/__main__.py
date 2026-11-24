# Compare receiver-reported DOP with DOP computed from the SATVIS2 geometry.

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.satellite_monitor import constellation_of
from um982py.capture import latest_epoch, record_epoch
from um982py.commands import Log
from um982py.geometry import (
    DilutionOfPrecision,
    ReportedDilution,
    SatelliteGeometry,
    geometry_from_record,
)
from um982py.messages.record import Record

_REPORTED_TIMEOUT = 0.2
_REPORTED_LOG = {"PSRDOP": Log.PSRDOP, "RTKDOP": Log.RTKDOP}


# PSRDOP/RTKDOP satellite lists use the offset PRNs of the N4 manual table
# "Satellite PRN Number (with Offset)"; SATVIS2 numbers GLONASS as slot + 37.
_OFFSET_RANGES = (
    (1, 32, "GPS", 0),
    (33, 42, "QZSS", 160),
    (43, 66, "GLONASS", -5),
    (75, 110, "GALILEO", -74),
    (161, 223, "BEIDOU", -160),
)


def satvis_identity(offset_prn: int) -> tuple[str, int] | None:
    """Constellation and SATVIS2 PRN of a PSRDOP list entry, or ``None``."""
    for low, high, constellation, shift in _OFFSET_RANGES:
        if low <= offset_prn <= high:
            return constellation, offset_prn + shift
    return None


def receiver_set_geometry(
    frames: Sequence[Record], used: Sequence[int]
) -> tuple[list[tuple[str, SatelliteGeometry]], list[int]]:
    """Geometry of the receiver's own solution satellites and unmatched PRNs."""
    sky = {
        (str(constellation_of(frame)), satellite.integer("prn")): SatelliteGeometry(
            azimuth=satellite.real("azimuth"), elevation=satellite.real("elevation")
        )
        for frame in frames
        for satellite in frame.records("satellites")
    }
    matched: list[tuple[str, SatelliteGeometry]] = []
    missing: list[int] = []
    for offset_prn in used:
        identity = satvis_identity(offset_prn)
        if identity is None or identity not in sky:
            missing.append(offset_prn)
        else:
            matched.append((identity[0], sky[identity]))
    return matched, missing


def _parser() -> ExampleParser:
    parser = ExampleParser(prog="python -m examples.dop_geometry", description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--mask",
        type=float,
        default=5.0,
        help="elevation mask in degrees when the receiver reports none",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(
            f"dop_geometry debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def _payload(
    computed: DilutionOfPrecision,
    reported: ReportedDilution | None,
    mask: float,
    *,
    clock_groups: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "elevation_mask": mask,
        "clock_groups": sorted(set(clock_groups)),
        "geometry": "unweighted visible SATVIS2 satellites",
        "computed": {
            "gdop": computed.gdop,
            "pdop": computed.pdop,
            "hdop": computed.hdop,
            "vdop": computed.vdop,
            "tdop": computed.tdop,
        },
        "receiver": None,
        "difference": None,
    }
    if reported is None:
        return payload
    payload["receiver"] = {
        "source": reported.source,
        "gdop": reported.gdop,
        "pdop": reported.pdop,
        "hdop": reported.hdop,
        "tdop": reported.tdop,
        "elevation_mask": reported.elevation_mask,
        "satellites": reported.satellites,
    }
    payload["difference"] = {
        "gdop": computed.gdop - reported.gdop if len(set(clock_groups)) == 1 else None,
        "pdop": computed.pdop - reported.pdop,
        "hdop": computed.hdop - reported.hdop,
        "tdop": computed.tdop - reported.tdop if len(set(clock_groups)) == 1 else None,
    }
    return payload


def _add_receiver_set(
    payload: dict[str, object],
    frames: Sequence[Record],
    reported: ReportedDilution,
    record: Record,
) -> None:
    """Compare the receiver's DOP with DOP of the satellites it reports using."""
    listed = record.get("sats_list")
    used = (
        [value for value in listed if isinstance(value, int)]
        if isinstance(listed, tuple)
        else []
    )
    matched, missing = receiver_set_geometry(frames, used)
    groups = [group for group, _ in matched]
    entry: dict[str, object] = {
        "satellites": len(used),
        "matched": len(matched),
        "unmatched_prns": missing,
        "clock_groups": sorted(set(groups)),
        "computed": None,
    }
    payload["receiver_set"] = entry
    payload["difference_basis"] = "all visible satellites"
    if not used or missing:
        return
    try:
        own = DilutionOfPrecision.from_geometry(
            [geometry for _, geometry in matched], clock_groups=groups
        )
    except ValueError:
        return
    entry["computed"] = {
        "gdop": own.gdop,
        "pdop": own.pdop,
        "hdop": own.hdop,
        "vdop": own.vdop,
        "tdop": own.tdop,
    }
    single = len(set(groups)) == 1
    payload["difference_basis"] = "receiver solution satellites"
    payload["difference"] = {
        "gdop": own.gdop - reported.gdop if single else None,
        "pdop": own.pdop - reported.pdop,
        "hdop": own.hdop - reported.hdop,
        "tdop": own.tdop - reported.tdop if single else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect one SATVIS2 epoch and report computed against reported DOP."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"dop_geometry debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    captured = capture_records(
        args,
        [Log.SATVIS2, Log.PSRDOP, Log.RTKDOP],
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    frames = latest_epoch(captured["SATVIS2"])
    reported = None
    reported_record = None
    for name in ("PSRDOP", "RTKDOP"):
        matching = [
            record
            for record in captured[name]
            if frames and abs(record_epoch(record) - record_epoch(frames[0])) < 0.01
        ]
        if matching:
            reported_record = matching[-1]
            reported = ReportedDilution.from_record(reported_record, name)
            break
    mask = reported.elevation_mask if reported is not None else args.mask
    grouped = [
        (str(constellation_of(frame)), satellite)
        for frame in frames
        for satellite in geometry_from_record(frame, mask)
    ]
    groups = [group for group, _ in grouped]
    satellites = [satellite for _, satellite in grouped]
    try:
        computed = DilutionOfPrecision.from_geometry(satellites, clock_groups=groups)
    except ValueError as error:
        write_json(
            {
                "status": "insufficient_data",
                "satellites": len(satellites),
                "reason": str(error),
                "clock_groups": sorted(set(groups)),
            },
            args.json,
        )
        return 1
    reported_text = (
        f"; receiver {reported.source} PDOP {reported.pdop:.2f}" if reported else ""
    )
    print(
        f"DOP: computed PDOP {computed.pdop:.2f} (GDOP {computed.gdop:.2f}) "
        f"from {len(satellites)} satellites above {mask:g} deg" + reported_text,
        file=sys.stderr,
    )
    payload = _payload(computed, reported, mask, clock_groups=groups)
    if reported is not None and reported_record is not None:
        _add_receiver_set(payload, frames, reported, reported_record)
    payload["gps_seconds"] = record_epoch(frames[0])
    payload["visible_satellites"] = len(satellites)
    payload["common_clock_assumption"] = asdict(
        DilutionOfPrecision.from_geometry(satellites)
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
