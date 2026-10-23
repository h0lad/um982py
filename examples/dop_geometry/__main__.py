"""Compare receiver-reported DOP with DOP computed from the SATVIS2 geometry."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.dop_geometry import (
    DilutionOfPrecision,
    ReportedDilution,
    geometry_from_records,
)
from um982py.capture import capture_records, latest_epoch, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record

_REPORTED_TIMEOUT = 0.2
_REPORTED_LOG = {"PSRDOP": FirmwareLog.PSRDOP, "RTKDOP": FirmwareLog.RTKDOP}


def _parser() -> ExampleParser:
    parser = ExampleParser(prog="python -m examples.dop_geometry", description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
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
    computed: DilutionOfPrecision, reported: ReportedDilution | None, mask: float
) -> dict[str, object]:
    payload: dict[str, object] = {
        "elevation_mask": mask,
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
        "gdop": computed.gdop - reported.gdop,
        "pdop": computed.pdop - reported.pdop,
        "hdop": computed.hdop - reported.hdop,
        "tdop": computed.tdop - reported.tdop,
    }
    return payload


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
        [FirmwareLog.SATVIS2, FirmwareLog.PSRDOP, FirmwareLog.RTKDOP],
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    frames = latest_epoch(captured["SATVIS2"])
    reported = None
    for name in ("PSRDOP", "RTKDOP"):
        matching = [
            record
            for record in captured[name]
            if frames and abs(record_epoch(record) - record_epoch(frames[0])) < 0.01
        ]
        if matching:
            reported = ReportedDilution.from_record(matching[-1], name)
            break
    mask = reported.elevation_mask if reported is not None else args.mask
    satellites = geometry_from_records(frames, mask)
    if len(satellites) < 4:
        write_json(
            {
                "status": "insufficient_data",
                "satellites": len(satellites),
                "reason": "at least four satellites at one epoch are required",
            },
            args.json,
        )
        return 1
    computed = DilutionOfPrecision.from_geometry(satellites)
    reported_text = (
        f"; receiver {reported.source} PDOP {reported.pdop:.2f}" if reported else ""
    )
    print(
        f"DOP: computed PDOP {computed.pdop:.2f} (GDOP {computed.gdop:.2f}) "
        f"from {len(satellites)} satellites above {mask:g} deg" + reported_text,
        file=sys.stderr,
    )
    write_json(_payload(computed, reported, mask), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
