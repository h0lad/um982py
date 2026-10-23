"""Estimate ECEF and local ENU motion from a position time series."""

import argparse
import json
import math
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from examples.research_session.compare_reference import _read
from um982py.capture import load_records, record_epoch
from um982py.commands import Log
from um982py.field_data import file_sha256
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="CSV: gps_seconds,x_m,y_m,z_m")
    source.add_argument("--replay", type=Path, help="capture containing BESTNAVXYZ")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reference-frame",
        required=True,
        help="frame independently established by user",
    )
    parser.add_argument("--max-gap-s", type=float, default=120)
    args = parser.parse_args(argv)
    if (
        not args.reference_frame.strip()
        or not math.isfinite(args.max_gap_s)
        or args.max_gap_s <= 0
    ):
        parser.error("frame and positive finite maximum gap are required")
    source_path = args.input or args.replay
    if source_path.resolve() == args.output.resolve():
        parser.error("output must differ from input")
    rejected = []
    observations: list[tuple[float, tuple[float, float, float] | None]] = []
    if args.replay:
        records = load_records(args.replay, Log.BESTNAVXYZ)
        for row in records:
            epoch = record_epoch(row)
            status = row["p_sol_status"]
            if status not in (0, "SOL_COMPUTED"):
                rejected.append(
                    {
                        "gps_seconds": epoch,
                        "solution_status": status,
                        "reason": "solution_not_computed",
                    }
                )
                observations.append((epoch, None))
                continue
            xyz = (row.real("p_x"), row.real("p_y"), row.real("p_z"))
            if not all(math.isfinite(value) for value in xyz):
                rejected.append(
                    {
                        "gps_seconds": epoch,
                        "solution_status": status,
                        "reason": "non_finite_position",
                    }
                )
                observations.append((epoch, None))
                continue
            if xyz == (0.0, 0.0, 0.0):
                rejected.append(
                    {
                        "gps_seconds": epoch,
                        "solution_status": status,
                        "reason": "undefined_ecef_position",
                    }
                )
                observations.append((epoch, None))
                continue
            observations.append((epoch, xyz))
        if any(not math.isfinite(epoch) for epoch, _ in observations) or any(
            b[0] <= a[0] for a, b in pairwise(observations)
        ):
            raise ValueError("position epochs must be strictly increasing")
    else:
        observations = [
            (row[0], (row[1], row[2], row[3])) for row in _read(source_path)
        ]
    origin = next((xyz for _, xyz in observations if xyz is not None), None)
    if origin is None:
        raise ValueError("position series is empty")
    lat, lon, _ = geodetic_from_ecef(*origin)
    output = []
    previous = None
    interrupted = False
    for epoch, position in observations:
        if position is None:
            previous = None
            interrupted = True
            continue
        displacement = (
            position[0] - origin[0],
            position[1] - origin[1],
            position[2] - origin[2],
        )
        enu = enu_from_ecef(*displacement, lat, lon)
        velocity = None
        reason = "invalid_position_epoch" if interrupted else "first_position"
        if previous is not None:
            dt = epoch - previous[0]
            if dt <= args.max_gap_s:
                velocity = (
                    (position[0] - previous[1][0]) / dt,
                    (position[1] - previous[1][1]) / dt,
                    (position[2] - previous[1][2]) / dt,
                )
                reason = None
            else:
                reason = "gap_exceeded"
        output.append(
            {
                "gps_seconds": epoch,
                "ecef_m": position,
                "displacement_ecef_m": displacement,
                "displacement_enu_m": enu,
                "velocity_ecef_mps": velocity,
                "velocity_unavailable_reason": reason,
                "velocity_enu_mps": enu_from_ecef(*velocity, lat, lon)
                if velocity
                else None,
            }
        )
        previous = (epoch, position)
        interrupted = False
    result = {
        "reference_frame_supplied_by_user": args.reference_frame,
        "origin_ecef_m": origin,
        "input_sha256": file_sha256(source_path),
        "max_gap_s": args.max_gap_s,
        "samples": output,
        "rejected_position_epochs": rejected,
        "uncertainty": None,
        "limitations": (
            "First position is the local origin, not surveyed truth. Velocity is "
            "a two-epoch finite difference, and frame, antenna and covariance are "
            "not independently validated."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
