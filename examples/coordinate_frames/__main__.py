"""Cross-check a BSLNENUHD baseline against the BESTXYZ antenna position."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.coordinate_frames import (
    Baseline,
    Geodetic,
    antenna_position,
    round_trip_baseline,
)
from um982py.antenna import AntennaLog
from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record

_POSITION = FirmwareLog.BESTXYZ.read()
_BASELINE = FirmwareLog.BSLNENUHD.read()


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.coordinate_frames", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=10.0, help="collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
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
            f"coordinate_frames debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def _baseline_payload(baseline: Baseline) -> dict[str, float]:
    return {
        "east": baseline.east,
        "north": baseline.north,
        "up": baseline.up,
        "length": baseline.length,
        "azimuth": baseline.azimuth,
        "elevation": baseline.elevation,
    }


def _payload(position: Geodetic, reported: Baseline) -> dict[str, object]:
    recovered = round_trip_baseline(position, reported)
    antenna = antenna_position(position, reported)
    return {
        "origin": {
            "latitude": position.latitude,
            "longitude": position.longitude,
            "height": position.height,
        },
        "reported": _baseline_payload(reported),
        "recovered": _baseline_payload(recovered),
        "residual": {
            "east": recovered.east - reported.east,
            "north": recovered.north - reported.north,
            "up": recovered.up - reported.up,
        },
        "antenna": {
            "latitude": antenna.latitude,
            "longitude": antenna.longitude,
            "height": antenna.height,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Read one BESTXYZ position and one BSLNENUHD baseline, then cross-check."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"coordinate_frames debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    logs = [FirmwareLog.BESTXYZ, FirmwareLog.BSLNENUHD]
    secondary = args.antenna in ("secondary", "2")
    anchor = AntennaLog(Log.BESTNAVXYZ, Log.BESTNAVXYZ)
    captured = capture_records(
        args,
        [*logs, anchor] if secondary else logs,
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    positions = captured["BESTXYZ"]
    baselines = captured["BSLNENUHD"]
    position_record = positions[-1] if positions else None
    baseline_record = baselines[-1] if baselines else None
    if position_record is None or baseline_record is None:
        parser.error(
            "BESTXYZ and BSLNENUHD records are required; replay a combined capture"
        )
    origin = position_record
    if secondary:
        anchors = captured["BESTNAVXYZ"]
        if not anchors:
            parser.error("the dual-antenna baseline requires its primary origin")
        origin = anchors[-1]
    payload = _payload(
        Geodetic.from_position_record(origin),
        Baseline.from_baseline_record(baseline_record),
    )
    if secondary:
        selected = Geodetic.from_position_record(position_record)
        payload["selected_antenna"] = 2
        payload["selected_position"] = {
            "latitude": selected.latitude,
            "longitude": selected.longitude,
            "height": selected.height,
        }
    residual = payload["residual"]
    if isinstance(residual, dict):
        print(
            f"Coordinate frames: residual east {residual['east']:.4f} m, "
            f"north {residual['north']:.4f} m, up {residual['up']:.4f} m",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
