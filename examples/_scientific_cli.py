"""CSV front end for reproducible scientific calculations."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from um982py.field_data import file_sha256
from um982py.science_experiments import (
    noise_multipath_summary,
    orbit_position_effect,
    phase_detrended,
    slip_detection_matrix,
    tec_phase_change,
    tec_spatial_summary,
    uncertainty_coverage,
)


def read_csv_rows(path: str) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError("CSV must have unique column headers")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    return rows


def read_finite_number(row: dict[str, str], name: str) -> float:
    value = float(row[name])
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def analyze_rows(
    name: str, rows: list[dict[str, str]], args: argparse.Namespace
) -> object:
    if name == "spatial_tec":
        station_a_changes: list[float] = []
        station_b_changes: list[float] = []
        for row in rows:
            high_frequency = read_finite_number(row, "high_hz")
            low_frequency = read_finite_number(row, "low_hz")
            for station, changes in (
                ("a", station_a_changes),
                ("b", station_b_changes),
            ):
                changes.append(
                    tec_phase_change(
                        read_finite_number(row, f"{station}_high_before_m"),
                        read_finite_number(row, f"{station}_low_before_m"),
                        read_finite_number(row, f"{station}_high_after_m"),
                        read_finite_number(row, f"{station}_low_after_m"),
                        high_frequency,
                        low_frequency,
                    )
                )
        return tec_spatial_summary(station_a_changes, station_b_changes)
    if name == "noise_multipath":
        shared = [
            read_finite_number(row, "difference_m")
            for row in rows
            if row["kind"] == "shared"
        ]
        separate = [
            read_finite_number(row, "difference_m")
            for row in rows
            if row["kind"] == "separate"
        ]
        repeat = [row for row in rows if row["kind"] == "repeat"]
        if any(row["kind"] not in ("shared", "separate", "repeat") for row in rows):
            raise ValueError("kind must be shared, separate or repeat")
        return noise_multipath_summary(
            shared,
            separate,
            [read_finite_number(row, "day1_m") for row in repeat],
            [read_finite_number(row, "day2_m") for row in repeat],
        )
    if name == "multifrequency_slips":
        if len(rows) != 1:
            raise ValueError("one frequency row is required")
        return slip_detection_matrix(
            [read_finite_number(rows[0], f"f{i}_hz") for i in (1, 2, 3)],
            args.max_cycles,
            args.gf_threshold_m,
            args.closure_threshold_m,
        )
    if name == "uncertainty_coverage":
        return {
            axis: uncertainty_coverage(
                [read_finite_number(row, f"{axis}_error_m") for row in rows],
                [read_finite_number(row, f"{axis}_sigma_m") for row in rows],
                args.multiplier,
            )
            for axis in ("east", "north", "up")
        }
    if name == "phase_fluctuations":
        arcs: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            arc_id = row["arc"]
            if not arc_id:
                raise ValueError("arc identifiers must not be empty")
            arcs.setdefault(arc_id, []).append(row)
        return {
            arc_id: phase_detrended(
                [read_finite_number(row, "time_s") for row in arc_rows],
                [read_finite_number(row, "phase_m") for row in arc_rows],
                args.max_gap_s,
            )
            for arc_id, arc_rows in arcs.items()
        }
    if name == "orbit_position_effect":
        return orbit_position_effect(
            [[read_finite_number(row, f"u_{axis}") for axis in "xyz"] for row in rows],
            [[read_finite_number(row, f"d{axis}_m") for axis in "xyz"] for row in rows],
            [read_finite_number(row, "clock_delta_s") for row in rows],
            [read_finite_number(row, "weight") for row in rows],
        )
    raise ValueError("unknown experiment")


def main(name: str) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, help="prepared CSV input described in the README"
    )
    parser.add_argument("--json", help="output JSON file, defaulting to stdout")
    if name == "multifrequency_slips":
        parser.add_argument("--max-cycles", type=int, default=1)
        parser.add_argument("--gf-threshold-m", type=float, default=0.05)
        parser.add_argument("--closure-threshold-m", type=float, default=0.05)
    if name == "uncertainty_coverage":
        parser.add_argument("--multiplier", type=float, default=1.0)
    if name == "phase_fluctuations":
        parser.add_argument("--max-gap-s", type=float, default=2.0)
    args = parser.parse_args()
    try:
        result = analyze_rows(name, read_csv_rows(args.input), args)
        output = (
            json.dumps(
                {
                    "experiment": name,
                    "input": args.input,
                    "input_sha256": file_sha256(Path(args.input)),
                    "assumptions": {
                        "phase_fluctuations": [
                            "Phase is range-increasing metres on continuous arcs.",
                            "Linear detrending is applied independently to each arc.",
                        ],
                        "orbit_position_effect": [
                            "Rows share one epoch and compatible conventions.",
                            "Satellite deltas are perturbed minus reference in ECEF.",
                        ],
                    }.get(name, []),
                    "parameters": {
                        k: v
                        for k, v in vars(args).items()
                        if k not in ("input", "json")
                    },
                    "result": result,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        if args.json:
            Path(args.json).write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
