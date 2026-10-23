"""Estimate a vertical-motion spectrum from a regularly sampled buoy track."""

import argparse
import csv
import json
import math
from collections.abc import Sequence
from pathlib import Path

from examples.doppler_velocity import SPECTRAL_FLOOR_HZ, wave_spectrum
from um982py.field_data import file_sha256, nearest_epoch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", type=Path, help="CSV gps_seconds,vertical_velocity_mps"
    )
    source.add_argument("--journey", type=Path, help="examples.journey_track JSON")
    parser.add_argument("--interval-s", type=float, required=True)
    parser.add_argument("--window-samples", type=int, default=256)
    parser.add_argument("--min-frequency-hz", type=float, required=True)
    parser.add_argument("--max-frequency-hz", type=float, required=True)
    parser.add_argument("--tolerance-s", type=float, default=0.01)
    parser.add_argument(
        "--reference", type=Path, help="CSV gps_seconds,significant_height_m"
    )
    parser.add_argument("--match-window-s", type=float, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.interval_s)
        or args.interval_s <= 0
        or not 8 <= args.window_samples <= 2048
        or not math.isfinite(args.tolerance_s)
        or not 0 <= args.tolerance_s < args.interval_s
        or not math.isfinite(args.match_window_s)
        or args.match_window_s < 0
        or not math.isfinite(args.min_frequency_hz)
        or not math.isfinite(args.max_frequency_hz)
        or not 0 < args.min_frequency_hz <= args.max_frequency_hz
        or args.max_frequency_hz > 1 / (2 * args.interval_s)
    ):
        parser.error(
            "invalid interval, tolerance, matching window or window size (8..2048)"
        )
    frequencies = [
        index / (args.window_samples * args.interval_s)
        for index in range(1, args.window_samples // 2 + 1)
        if index / (args.window_samples * args.interval_s) > SPECTRAL_FLOOR_HZ
    ]
    if not any(
        args.min_frequency_hz <= f <= args.max_frequency_hz for f in frequencies
    ):
        parser.error("frequency band contains no resolved spectral bin")
    path = args.input or args.journey
    inputs = [path, *([args.reference] if args.reference else [])]
    if args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must differ from inputs")
    if args.input:
        with args.input.open(newline="", encoding="utf-8") as stream:
            data = [
                (
                    float(r["gps_seconds"]),
                    float(r["vertical_velocity_mps"])
                    if r["vertical_velocity_mps"]
                    else None,
                )
                for r in csv.DictReader(stream)
            ]
    else:
        report = json.loads(path.read_text(encoding="utf-8"))
        data = [
            (
                float(row["gps_seconds"]),
                float(row["vertical_speed_mps"])
                if row.get("vertical_speed_mps") is not None
                else None,
            )
            for row in report["samples"]
        ]
    reference: list[tuple[float, float]] = []
    if args.reference:
        with args.reference.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                epoch, height = (
                    float(row["gps_seconds"]),
                    float(row["significant_height_m"]),
                )
                if not math.isfinite(epoch) or not math.isfinite(height) or height < 0:
                    raise ValueError(
                        "reference epochs and non-negative heights must be finite"
                    )
                reference.append((epoch, height))
    reference.sort()
    reference_times = [sample[0] for sample in reference]
    chunks: list[list[tuple[float, float]]] = []
    arc: list[tuple[float, float]] = []
    last_time = None
    invalid = gaps = 0
    for epoch, velocity in data:
        if not math.isfinite(epoch) or (last_time is not None and epoch <= last_time):
            raise ValueError("sample epochs must be finite and strictly increasing")
        if arc and abs(epoch - arc[-1][0] - args.interval_s) > args.tolerance_s:
            chunks.append(arc)
            arc = []
            gaps += 1
        if velocity is None or not math.isfinite(velocity):
            invalid += 1
            if arc:
                chunks.append(arc)
                arc = []
        else:
            arc.append((epoch, velocity))
        last_time = epoch
    if arc:
        chunks.append(arc)
    windows = []
    discarded = 0
    for arc in chunks:
        for start in range(0, len(arc), args.window_samples):
            block = arc[start : start + args.window_samples]
            if len(block) < args.window_samples:
                discarded += len(block)
                continue
            samples = [row[1] for row in block]
            spectrum = tuple(
                (f, power)
                for f, power in wave_spectrum(samples, args.interval_s)
                if args.min_frequency_hz <= f <= args.max_frequency_hz
            )
            peak_power = max(power for _, power in spectrum)
            bandwidth = 1 / (len(block) * args.interval_s)
            m0 = math.fsum(power * bandwidth for _, power in spectrum)
            m2 = math.fsum(f * f * power * bandwidth for f, power in spectrum)
            height = 4 * math.sqrt(m0)
            peak_period = (
                1 / max(spectrum, key=lambda item: item[1])[0]
                if peak_power > 0
                else None
            )
            mean_period = math.sqrt(m0 / m2) if m2 > 0 else None
            midpoint = (block[0][0] + block[-1][0]) / 2
            nearest = nearest_epoch(reference, reference_times, midpoint)
            match = (
                nearest
                if nearest is not None
                and abs(nearest[0] - midpoint) <= args.match_window_s
                else None
            )
            windows.append(
                {
                    "start_gps_seconds": block[0][0],
                    "end_gps_seconds": block[-1][0],
                    "sample_count": len(block),
                    "frequency_resolution_hz": 1 / (len(block) * args.interval_s),
                    "nyquist_hz": 1 / (2 * args.interval_s),
                    "significant_height_m": height,
                    "peak_period_s": peak_period,
                    "mean_period_s": mean_period,
                    "reference_gps_seconds": match[0] if match else None,
                    "reference_height_m": match[1] if match else None,
                    "height_difference_m": height - match[1] if match else None,
                    "displacement_spectrum": [
                        {"frequency_hz": f, "density_m2_per_hz": p} for f, p in spectrum
                    ],
                }
            )
    result = {
        "windows": windows,
        "gap_count": gaps,
        "invalid_velocity_samples": invalid,
        "discarded_incomplete_samples": discarded,
        "input_sha256": file_sha256(path),
        "reference_sha256": file_sha256(args.reference) if args.reference else None,
        "parameters": {
            "interval_s": args.interval_s,
            "tolerance_s": args.tolerance_s,
            "window_samples": args.window_samples,
            "min_frequency_hz": args.min_frequency_hz,
            "max_frequency_hz": args.max_frequency_hz,
            "match_window_s": args.match_window_s,
        },
        "limitations": (
            "The spectrum describes antenna vertical velocity, not necessarily "
            "sea-surface motion. Buoy tilt, draft, mounting and GNSS noise are "
            "uncorrected. Mean velocity is removed, a Hann window is used, and "
            "the displacement spectrum is obtained by dividing by squared "
            "angular frequency. Finite windows and low-frequency noise limit "
            "interpretation. Reference timing and comparability must be "
            "independently verified."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if windows else 1


if __name__ == "__main__":
    raise SystemExit(main())
