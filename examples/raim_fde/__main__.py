# Run residual chi-square fault detection and exclusion.

from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records, selected_log
from examples.raim_fde import RaimResult, raim_fde
from examples.wls_position import (
    geodetic_position_error,
)
from examples.wls_position import measurements as wls_measurements
from um982py.capture import (
    decode_records,
    read_frames,
    record_epoch,
    select_position_pair,
)
from um982py.commands import Log
from um982py.geodesy import geodetic_from_ecef, receiver_ecef
from um982py.measurement import gps_epoch


def _payload(
    result: RaimResult,
    truth: tuple[float, float, float],
    latitude: float,
    longitude: float,
    measurement_count: int,
) -> dict[str, object]:
    error = geodetic_position_error(
        result.solution, latitude, longitude, truth[0], truth[1], truth[2]
    )
    return {
        "integrity_passed": result.integrity_passed,
        "model": "illustrative GPS L1 residual check; not an integrity certification",
        "measurement_count": measurement_count,
        "alarm": result.alarm,
        "test_statistic": result.test_statistic,
        "threshold": result.threshold,
        "excluded": [
            {"system": system.name, "prn": prn} for system, prn in result.excluded
        ],
        "protection_levels": {"hpl": result.hpl, "vpl": result.vpl},
        "protection_level_interpretation": (
            "Illustrative single-fault slope bounds at the detection threshold; "
            "no missed-detection probability or multiple-fault risk allocation. "
            "These are not calibrated operational protection levels."
        ),
        "difference_to_receiver_m": {
            "horizontal": error.horizontal,
            "vertical": error.vertical,
        },
        "error_reference": "receiver-reported position",
        "position_ecef_covariance_m2": result.solution.ecef_covariance_m2,
        "position_ecef_standard_deviation_m": result.solution.ecef_standard_deviation_m,
        "position_uncertainty_note": (
            "Formal covariance assumes independent pseudorange errors and excludes "
            "systematic errors; protection levels are not standard deviations"
        ),
        "position": {
            "x": result.solution.x,
            "y": result.solution.y,
            "z": result.solution.z,
        },
        "clock_bias_seconds": result.solution.clock_bias,
        "converged": result.solution.converged,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run RAIM fault detection and protection levels on one RANGE epoch."""
    parser = ExampleParser(
        prog="python -m examples.raim_fde",
        description="Residual chi-square RAIM FDE with HPL and VPL",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ephemeris",
        type=Path,
        default=None,
        help="captured ephemeris frames for replay",
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
        "--range-model-sigma",
        type=float,
        default=0.0,
        help="additional independent pseudorange model uncertainty in metres",
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
    if not math.isfinite(args.range_model_sigma) or args.range_model_sigma < 0:
        parser.error("range model sigma must be finite and nonnegative")
    debug_header(args, "raim_fde")
    if args.replay is None:
        logs: list[Log] = [
            Log.RANGE,
            Log.BESTPOS,
            Log.GPSEPH,
        ]
        captured = capture_records(
            args,
            logs,
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("raim_fde") if args.debug else None,
        )
        range_records, position_records = captured["RANGE"], captured["BESTPOS"]
        ephemeris_frames = [
            record.message
            for record in captured["GPSEPH"]
            if record.message is not None
        ]
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
        range_records = decode_records(range_frames, selected_log(args, Log.RANGE))
        position_records = decode_records(
            position_frames, selected_log(args, Log.BESTPOS)
        )
        if not position_records:
            position_records = decode_records(
                position_frames, selected_log(args, Log.BESTXYZ)
            )
    if not range_records or not position_records:
        parser.error("a RANGE frame and a BESTPOS/BESTXYZ frame are required")
    range_record, position = select_position_pair(
        range_records, position_records, args.position_tolerance
    )
    if range_record.message is None:
        parser.error("RANGE frame carries no timestamp")
    epoch = gps_epoch(range_record.message) % 604800.0
    absolute_epoch = record_epoch(range_record)
    ephemerides = wls_measurements.select_gps_ephemerides(
        decode_records(ephemeris_frames, Log.GPSEPH),
        absolute_epoch,
        ranges=range_record,
    )
    truth = receiver_ecef(position)
    observations = wls_measurements.gps_l1_measurements(
        range_record, ephemerides, epoch
    )
    if args.range_model_sigma:
        observations = tuple(
            replace(
                observation,
                pseudorange_std=math.hypot(
                    observation.pseudorange_std, args.range_model_sigma
                ),
            )
            for observation in observations
        )
    result = raim_fde(observations, (*truth, 0.0))
    latitude, longitude = (
        (position.real("lat"), position.real("lon"))
        if "lat" in position
        else geodetic_from_ecef(*truth)[:2]
    )
    payload = _payload(result, truth, latitude, longitude, len(observations))
    payload["range_model_sigma_m"] = args.range_model_sigma
    error = payload["difference_to_receiver_m"]
    if isinstance(error, dict):
        print(
            f"RAIM: {len(observations)} GPS L1 observations; "
            f"alarm={payload['alarm']}; "
            f"horizontal receiver difference {error['horizontal']:.3f} m, "
            f"vertical difference {error['vertical']:.3f} m",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
