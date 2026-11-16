# Demonstrate ENU/ECEF conversion with an epoch-matched antenna baseline.

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from copy import copy

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records, selected_log
from examples.coordinate_frames import (
    Baseline,
    Geodetic,
    antenna_position,
    round_trip_baseline,
)
from um982py.antenna import AntennaLog
from um982py.capture import record_epoch, select_position
from um982py.commands import Log
from um982py.messages.record import Record

_POSITION = Log.BESTXYZ.read()
_BASELINE = Log.BSLNENUHD.read()


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.coordinate_frames", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=10.0, help="collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--position-tolerance",
        type=float,
        default=1.0,
        help="maximum position/baseline epoch offset in seconds",
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


def _position_precision(record: Record) -> dict[str, object]:
    """Report the receiver's ECEF component standard deviations."""
    return {
        "ecef_standard_deviation_m": [
            record.real(name) if name in record else None
            for name in ("p_x_std", "p_y_std", "p_z_std")
        ],
        "source": record.name,
    }


def _payload(position: Geodetic, reported: Baseline) -> dict[str, object]:
    recovered = round_trip_baseline(position, reported)
    antenna = antenna_position(position, reported)
    return {
        "validation": (
            "coordinate round trip; not an independent baseline accuracy check"
        ),
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
    logs = [selected_log(args, Log.BESTXYZ), Log.BSLNENUHD]
    secondary = (args.antenna in ("secondary", "2")) != args.swap_antennas
    anchor = AntennaLog(Log.BESTNAVXYZ, Log.BESTNAVXYZ)
    capture_args = copy(args)
    capture_args.antenna = "primary"
    capture_args.swap_antennas = False
    captured = capture_records(
        capture_args,
        [*logs, anchor] if secondary else logs,
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    positions = captured["BESTXYZ"]
    baselines = captured["BSLNENUHD"]
    valid_baselines = [
        record
        for record in baselines
        if record.get("p_sol_status") in (0, "SOL_COMPUTED")
        and all(
            math.isfinite(record.real(name))
            for name in ("delta_1", "delta_2", "delta_3")
        )
    ]
    if not positions or not valid_baselines:
        parser.error(
            "BESTXYZ and computed BSLNENUHD records are required; "
            "replay a combined capture"
        )
    baseline_record = max(valid_baselines, key=record_epoch)
    epoch = record_epoch(baseline_record)
    position_record = select_position(positions, epoch, args.position_tolerance)
    origin = position_record
    if secondary:
        anchors = captured["BESTNAVXYZ"]
        if not anchors:
            parser.error("the dual-antenna baseline requires its primary origin")
        origin = select_position(anchors, epoch, args.position_tolerance)
    payload = _payload(
        Geodetic.from_position_record(origin),
        Baseline.from_baseline_record(baseline_record),
    )
    payload["origin_precision"] = _position_precision(origin)
    payload["epoch"] = epoch
    payload["position_epoch_offset_s"] = record_epoch(origin) - epoch
    payload["baseline_direction"] = "physical ANT1 to ANT2 in the ANT1 local frame"
    payload["antenna_precision"] = None
    payload["precision_note"] = (
        "Receiver ECEF standard deviations describe the origin; derived antenna "
        "uncertainty requires baseline and cross-covariance information."
    )
    if secondary:
        selected = Geodetic.from_position_record(position_record)
        payload["selected_antenna"] = 2
        payload["selected_position"] = {
            "latitude": selected.latitude,
            "longitude": selected.longitude,
            "height": selected.height,
        }
        payload["selected_position_precision"] = _position_precision(position_record)
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
