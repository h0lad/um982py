"""CSV front end for reproducible scientific calculations."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from um982py.science_experiments import (
    noise_multipath_summary,
    orbit_position_effect,
    phase_detrended,
    slip_detection_matrix,
    tec_phase_change,
    tec_spatial_summary,
    uncertainty_coverage,
)


def read_rows(path: str) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError("CSV must have unique column headers")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    return rows


def num(row: dict[str, str], name: str) -> float:
    v = float(row[name])
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


def analyze(name: str, rows: list[dict[str, str]], args: argparse.Namespace) -> object:
    if name == "spatial_tec":
        a: list[float] = []
        b: list[float] = []
        for row in rows:
            f1, f2 = num(row, "high_hz"), num(row, "low_hz")
            for station, result in (("a", a), ("b", b)):
                result.append(
                    tec_phase_change(
                        num(row, f"{station}_high_before_m"),
                        num(row, f"{station}_low_before_m"),
                        num(row, f"{station}_high_after_m"),
                        num(row, f"{station}_low_after_m"),
                        f1,
                        f2,
                    )
                )
        return tec_spatial_summary(a, b)
    if name == "noise_multipath":
        shared = [num(r, "difference_m") for r in rows if r["kind"] == "shared"]
        separate = [num(r, "difference_m") for r in rows if r["kind"] == "separate"]
        repeat = [r for r in rows if r["kind"] == "repeat"]
        if any(r["kind"] not in ("shared", "separate", "repeat") for r in rows):
            raise ValueError("kind must be shared, separate or repeat")
        return noise_multipath_summary(
            shared,
            separate,
            [num(r, "day1_m") for r in repeat],
            [num(r, "day2_m") for r in repeat],
        )
    if name == "multifrequency_slips":
        if len(rows) != 1:
            raise ValueError("one frequency row is required")
        return slip_detection_matrix(
            [num(rows[0], f"f{i}_hz") for i in (1, 2, 3)],
            args.max_cycles,
            args.gf_threshold_m,
            args.closure_threshold_m,
        )
    if name == "uncertainty_coverage":
        return {
            axis: uncertainty_coverage(
                [num(r, f"{axis}_error_m") for r in rows],
                [num(r, f"{axis}_sigma_m") for r in rows],
                args.multiplier,
            )
            for axis in ("east", "north", "up")
        }
    if name == "phase_fluctuations":
        arcs: dict[str, list[dict[str, str]]] = {}
        for r in rows:
            key = r["arc"]
            if not key:
                raise ValueError("arc identifiers must not be empty")
            arcs.setdefault(key, []).append(r)
        return {
            key: phase_detrended(
                [num(r, "time_s") for r in values],
                [num(r, "phase_m") for r in values],
                args.max_gap_s,
            )
            for key, values in arcs.items()
        }
    if name == "orbit_position_effect":
        return orbit_position_effect(
            [[num(r, f"u_{axis}") for axis in "xyz"] for r in rows],
            [[num(r, f"d{axis}_m") for axis in "xyz"] for r in rows],
            [num(r, "clock_delta_s") for r in rows],
            [num(r, "weight") for r in rows],
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
        result = analyze(name, read_rows(args.input), args)
        output = (
            json.dumps(
                {
                    "experiment": name,
                    "input": args.input,
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
