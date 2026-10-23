"""Builds GPS broadcast states and capture wiring for velocity runs."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from um982py.capture import capture_logs, load_records, record_epoch
from um982py.commands import Log
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.experimental.gps_motion import (
    choose_ephemeris,
    doppler_measurement,
    phase_difference,
    solve_displacement,
    solve_velocity,
)
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef
from um982py.measurement import RangeSample, range_samples
from um982py.messages import Record
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.stats import Vector, is_continuous, norm, rms, subtract


def _observer(
    args: argparse.Namespace, positions: Sequence[Record], epoch: float
) -> Vector:
    if args.observer is not None:
        return args.observer[0], args.observer[1], args.observer[2]
    near = min(
        positions, key=lambda record: abs(record_epoch(record) - epoch), default=None
    )
    if near is None or abs(record_epoch(near) - epoch) > 2:
        raise ValueError(
            "supply --observer X Y Z or co-timed BESTXYZ records within 2s"
        )
    return near.real("p_x"), near.real("p_y"), near.real("p_z")


def _receiver_comparison(
    epoch: float,
    velocity: Vector,
    observer: Vector,
    records: Sequence[Record],
    *,
    tolerance: float,
) -> dict[str, object] | None:
    """Compare matched receiver speeds without claiming independent truth."""
    eligible = [
        row
        for row in records
        if row.get("v_sol_status") in (SolutionStatus.SOL_COMPUTED, "SOL_COMPUTED")
        and row.get("vel_type") in (PositionType.DOPPLER_VELOCITY, "DOPPLER_VELOCITY")
    ]
    near = min(eligible, key=lambda row: abs(record_epoch(row) - epoch), default=None)
    if near is None or abs(record_epoch(near) - epoch) > tolerance:
        return None
    latitude, longitude, _ = geodetic_from_ecef(*observer)
    east, north, up = enu_from_ecef(*velocity, latitude, longitude)
    horizontal = near.real("hor_spd")
    vertical = near.real("vert_spd")
    return {
        "receiver_epoch": record_epoch(near),
        "time_difference_s": record_epoch(near) - epoch,
        "receiver_latency_s": near.real("latency"),
        "receiver_age_s": near.real("age"),
        "receiver_horizontal_mps": horizontal,
        "receiver_vertical_mps": vertical,
        "horizontal_difference_mps": math.hypot(east, north) - horizontal,
        "vertical_difference_mps": up - vertical,
    }


def motion_main(name: str, argv: Sequence[str] | None) -> int:
    """Run a bounded GPS L1 Doppler or time-differenced phase experiment."""
    parser = experiment_parser(
        name, "GPS L1 motion with broadcast satellite and clock corrections"
    )
    parser.add_argument("--ephemeris", type=Path, help="additional GPSEPH wire capture")
    parser.add_argument(
        "--observer",
        type=float,
        nargs=3,
        metavar=("X", "Y", "Z"),
        help="approximate receiver ECEF metres",
    )
    parser.add_argument(
        "--truth-velocity",
        type=float,
        nargs=3,
        metavar=("VX", "VY", "VZ"),
        help="independently known constant ECEF velocity, m/s",
    )
    parser.add_argument("--max-gap", type=float, default=2.0)
    parser.add_argument(
        "--phase-tolerance",
        type=float,
        default=0.5,
        help="Doppler closure tolerance in metres",
    )
    parser.add_argument(
        "--sigma",
        type=float,
        default=0.5,
        help="assumed Doppler range-rate sigma in m/s",
    )
    if name == "doppler_velocity":
        parser.add_argument(
            "--compare-receiver",
            action="store_true",
            help="compare matched primary-antenna DOPPVEL solutions",
        )
        parser.add_argument("--receiver-tolerance", type=float, default=0.5)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, name)
    if args.max_gap <= 0 or args.phase_tolerance <= 0 or args.sigma <= 0:
        parser.error("gap, phase tolerance and sigma must be positive")
    compare_receiver = bool(getattr(args, "compare_receiver", False))
    if compare_receiver and args.receiver_tolerance < 0:
        parser.error("receiver tolerance must be nonnegative")
    logs: list[FirmwareLog | Log] = [FirmwareLog.RANGE, FirmwareLog.BESTXYZ, Log.GPSEPH]
    if compare_receiver:
        logs.append(FirmwareLog.DOPPVEL)
    data = capture_logs(
        args,
        logs,
        on_progress=progress_printer(name) if args.debug else None,
    )
    ephemerides = data["GPSEPH"] + (
        load_records(args.ephemeris, Log.GPSEPH) if args.ephemeris else ()
    )
    results: list[dict[str, object]] = []
    velocities: list[Vector] = []
    rejected: list[dict[str, object]] = []
    previous: dict[int, RangeSample] = {}
    previous_epoch: float | None = None
    for record in data["RANGE"]:
        epoch = record_epoch(record)
        if previous_epoch is not None and epoch <= previous_epoch:
            raise ValueError("RANGE epochs must increase strictly")
        samples = {
            sample.key.prn: sample
            for sample in range_samples(record)
            if sample.key.signal == 0
        }
        try:
            observer = _observer(args, data["BESTXYZ"], epoch)
            if name == "doppler_velocity":
                measurements = []
                for sample in samples.values():
                    try:
                        eph = choose_ephemeris(ephemerides, sample.key.prn, epoch)
                        measurements.append(
                            doppler_measurement(
                                sample, eph, observer, sigma_mps=args.sigma
                            )
                        )
                    except ValueError as failure:
                        rejected.append(
                            {
                                "epoch": epoch,
                                "prn": sample.key.prn,
                                "reason": str(failure),
                            }
                        )
                velocity = solve_velocity(measurements)
                result: dict[str, object] = {"epoch": epoch, **asdict(velocity)}
                if compare_receiver:
                    result["receiver_comparison"] = _receiver_comparison(
                        epoch,
                        velocity.velocity,
                        observer,
                        data["DOPPVEL"],
                        tolerance=args.receiver_tolerance,
                    )
                results.append(result)
                velocities.append(velocity.velocity)
            elif previous_epoch is not None:
                differences = []
                for prn, sample in samples.items():
                    before = previous.get(prn)
                    if before is None or not is_continuous(
                        before,
                        sample,
                        max_gap=args.max_gap,
                        phase_tolerance=args.phase_tolerance,
                    ):
                        rejected.append(
                            {
                                "epoch": epoch,
                                "prn": prn,
                                "reason": "missing or discontinuous phase arc",
                            }
                        )
                        continue
                    try:
                        eph = choose_ephemeris(ephemerides, prn, epoch)
                        differences.append(
                            phase_difference(before, sample, eph, observer)
                        )
                    except ValueError as failure:
                        rejected.append(
                            {"epoch": epoch, "prn": prn, "reason": str(failure)}
                        )
                displacement = solve_displacement(
                    differences, interval=epoch - previous_epoch
                )
                results.append(
                    {
                        "epoch": epoch,
                        "start_epoch": previous_epoch,
                        **asdict(displacement),
                    }
                )
                velocities.append(displacement.velocity_mps)
        except ValueError as failure:
            rejected.append({"epoch": epoch, "reason": str(failure)})
        previous, previous_epoch = samples, epoch
    truth = args.truth_velocity
    errors = (
        [
            norm(subtract(velocity, (truth[0], truth[1], truth[2])))
            for velocity in velocities
        ]
        if truth is not None
        else []
    )
    print(
        f"Motion: {len(results)} epochs, {len(rejected)} rejected",
        file=sys.stderr,
    )
    write_json(
        {
            "status": "ok" if results else "insufficient_data",
            "model": (
                "GPS L1 broadcast orbit/clock, transmit time and Earth "
                "rotation, without modelling atmosphere and phase wind-up changes"
            ),
            "ground_truth": "user-supplied constant velocity"
            if truth is not None
            else "not supplied, so no accuracy claim is made",
            "velocity_rmse_mps": rms(errors) if errors else None,
            "receiver_comparison_limitation": (
                "The receiver and solver share observations. Header epochs are "
                "matched without latency correction; receiver samples can be reused. "
                "This is not an independent accuracy check."
                if compare_receiver
                else None
            ),
            "epochs": results,
            "rejected": rejected,
            "next_step": None
            if results
            else (
                "record at least two locked epochs, matching healthy "
                "GPSEPH, and BESTXYZ or --observer"
            ),
        },
        args.json,
    )
    return 0 if results else 1
