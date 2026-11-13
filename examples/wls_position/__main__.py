"""Solve position from pseudoranges by weighted least squares."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records
from examples.wls_position import (
    PositionSolution,
    geodetic_position_error,
    solve_position,
)
from examples.wls_position import measurements as wls_measurements
from um982py.capture import decode_records, read_frames, record_epoch
from um982py.commands import Log
from um982py.geodesy import geodetic_from_ecef, receiver_ecef
from um982py.measurement import gps_epoch


def _solution_payload(
    solution: PositionSolution,
    truth: tuple[float, float, float],
    latitude: float,
    longitude: float,
    measurement_count: int,
) -> dict[str, object]:
    error = geodetic_position_error(
        solution, latitude, longitude, truth[0], truth[1], truth[2]
    )
    return {
        "model": (
            "GPS L1 broadcast solution with transmit-time and Earth-rotation "
            "corrections; atmosphere uncorrected"
        ),
        "measurement_count": measurement_count,
        "position": {
            "x": solution.x,
            "y": solution.y,
            "z": solution.z,
            "clock_bias_seconds": solution.clock_bias,
        },
        "difference_to_receiver_m": {
            "horizontal": error.horizontal,
            "vertical": error.vertical,
        },
        "error_reference": "receiver-reported position",
        "position_ecef_covariance_m2": solution.ecef_covariance_m2,
        "position_ecef_standard_deviation_m": solution.ecef_standard_deviation_m,
        "position_uncertainty_note": (
            "Formal covariance from independent pseudorange standard deviations; "
            "excludes atmospheric and other systematic errors. Null if unconverged."
        ),
        "iterations": solution.iterations,
        "converged": solution.converged,
        "residual_norms": list(solution.residual_norms),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Solve one weighted least-squares epoch against a BESTPOS position."""
    parser = ExampleParser(
        prog="python -m examples.wls_position",
        description="Weighted least-squares single-point positioning from RANGE",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ephemeris",
        type=Path,
        default=None,
        help="captured GPSEPH frames for replay",
    )
    parser.add_argument(
        "--position",
        type=Path,
        default=None,
        help="captured BESTPOS or BESTXYZ frame for replay",
    )
    parser.add_argument(
        "--position-tolerance",
        type=float,
        default=1.0,
        help="maximum receiver position epoch offset in seconds",
    )
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "wls_position")
    if args.replay is None:
        captured = capture_records(
            args,
            [Log.RANGE, Log.BESTPOS, Log.GPSEPH],
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("wls_position") if args.debug else None,
        )
        range_records, position_records = captured["RANGE"], captured["BESTPOS"]
        ephemeris_records = captured["GPSEPH"]
    else:
        range_frames = read_frames(args.replay)
        position_frames = (
            read_frames(args.position) if args.position is not None else range_frames
        )
        ephemeris_frames = (
            list(read_frames(args.ephemeris))
            if args.ephemeris is not None
            else list(range_frames)
        )
        range_records = decode_records(range_frames, Log.RANGE)
        position_records = decode_records(position_frames, Log.BESTPOS)
        if not position_records:
            position_records = decode_records(position_frames, Log.BESTXYZ)
        ephemeris_records = decode_records(ephemeris_frames, Log.GPSEPH)
    if not range_records or not position_records:
        parser.error("a RANGE frame and a BESTPOS/BESTXYZ frame are required")
    range_record = range_records[0]
    if range_record.message is None:
        parser.error("RANGE frame carries no timestamp")
    epoch = gps_epoch(range_record.message) % 604800.0
    absolute_epoch = record_epoch(range_record)
    ephemerides = wls_measurements.select_gps_ephemerides(
        ephemeris_records, absolute_epoch, ranges=range_record
    )
    measurements = wls_measurements.gps_l1_measurements(
        range_record, ephemerides, epoch
    )
    if not measurements:
        parser.error("no GPS L1 observations have a matching ephemeris")
    position = wls_measurements.select_position(
        position_records, absolute_epoch, args.position_tolerance
    )
    truth = receiver_ecef(position)
    solution = solve_position(measurements, (*truth, 0.0))
    latitude, longitude = (
        (position.real("lat"), position.real("lon"))
        if "lat" in position
        else geodetic_from_ecef(*truth)[:2]
    )
    payload = _solution_payload(solution, truth, latitude, longitude, len(measurements))
    error = payload["difference_to_receiver_m"]
    if isinstance(error, dict):
        print(
            f"WLS position: {len(measurements)} GPS L1 ranges; "
            f"horizontal receiver difference {error['horizontal']:.3f} m, "
            f"vertical difference {error['vertical']:.3f} m; "
            f"converged={payload['converged']}",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
