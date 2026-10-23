"""Compare GNSS-IR reflector heights with a water-level gauge."""

import argparse
import csv
import importlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from um982py.field_data import file_sha256, nearest_epoch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arcs", type=Path, nargs="+", required=True, help="GNSS-IR arc CSV files"
    )
    parser.add_argument("--antenna", choices=("ANT1", "ANT2"), required=True)
    parser.add_argument(
        "--antenna-elevation-m",
        type=float,
        required=True,
        help="surveyed antenna elevation above the supplied datum",
    )
    parser.add_argument(
        "--datum", required=True, help="vertical datum shared by antenna and gauge"
    )
    parser.add_argument(
        "--gauge",
        type=Path,
        help="CSV with gps_seconds,water_level_m in the supplied datum",
    )
    parser.add_argument(
        "--match-window-s",
        type=float,
        help="maximum midpoint-to-gauge offset in seconds, required with --gauge",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--plot", type=Path, help="optional water-level and residual figure"
    )
    args = parser.parse_args(argv)
    if (
        not args.datum.strip()
        or not math.isfinite(args.antenna_elevation_m)
        or (
            args.match_window_s is not None
            and (not math.isfinite(args.match_window_s) or args.match_window_s < 0)
        )
    ):
        parser.error(
            "provide a datum, finite elevation and non-negative matching window"
        )
    if args.gauge is not None and args.match_window_s is None:
        parser.error("--gauge requires an explicit --match-window-s")
    inputs = [*args.arcs, *([args.gauge] if args.gauge else [])]
    if args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must differ from every input")
    if args.plot is not None and args.plot.resolve() in {
        *(p.resolve() for p in inputs),
        args.output.resolve(),
    }:
        parser.error("plot must differ from inputs and report")
    gauge: list[tuple[float, float]] = []
    if args.gauge:
        with args.gauge.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                sample = float(row["gps_seconds"]), float(row["water_level_m"])
                if not all(math.isfinite(value) for value in sample):
                    raise ValueError("gauge epochs and levels must be finite")
                gauge.append(sample)
    gauge.sort()
    if any(a[0] == b[0] for a, b in pairwise(gauge)):
        raise ValueError("gauge epochs must be unique")
    gauge_times = [sample[0] for sample in gauge]
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    errors: list[float] = []
    for path in args.arcs:
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                if row["antenna"] != args.antenna:
                    continue
                if row["rejection"]:
                    rejected.append({"source": str(path), **row})
                    continue
                start, end, height = (
                    float(row[k]) for k in ("start_gps_s", "end_gps_s", "height_m")
                )
                if (
                    not all(math.isfinite(value) for value in (start, end, height))
                    or end < start
                    or height <= 0
                ):
                    raise ValueError("accepted arc has invalid time or height")
                epoch = (start + end) / 2
                nearest = nearest_epoch(gauge, gauge_times, epoch)
                match = (
                    nearest
                    if nearest is not None
                    and args.match_window_s is not None
                    and abs(nearest[0] - epoch) <= args.match_window_s
                    else None
                )
                level = args.antenna_elevation_m - height
                error = level - match[1] if match is not None else None
                if error is not None:
                    errors.append(error)
                accepted.append(
                    {
                        "source": str(path),
                        "system": row["system"],
                        "prn": row["prn"],
                        "signal": row["signal"],
                        "direction": row["direction"],
                        "start_gps_s": start,
                        "end_gps_s": end,
                        "midpoint_gps_s": epoch,
                        "reflector_height_m": height,
                        "water_level_m": level,
                        "gauge_gps_seconds": match[0] if match else None,
                        "gauge_level_m": match[1] if match else None,
                        "gauge_time_difference_s": epoch - match[0] if match else None,
                        "difference_m": error,
                    }
                )
    matched_epochs = Counter(
        row["gauge_gps_seconds"]
        for row in accepted
        if row["gauge_gps_seconds"] is not None
    )
    result = {
        "datum_supplied_by_user": args.datum,
        "antenna": args.antenna,
        "antenna_elevation_m": args.antenna_elevation_m,
        "match_window_s": args.match_window_s,
        "inputs": [{"path": str(p), "sha256": file_sha256(p)} for p in inputs],
        "accepted_arcs": sorted(
            accepted, key=lambda x: float(str(x["midpoint_gps_s"]))
        ),
        "rejected_arcs": rejected,
        "matched_count": len(errors),
        "unique_matched_gauge_epochs": len(matched_epochs),
        "reused_gauge_matches": sum(count - 1 for count in matched_epochs.values()),
        "mean_difference_m": math.fsum(errors) / len(errors) if errors else None,
        "rms_difference_m": math.sqrt(math.fsum(e * e for e in errors) / len(errors))
        if errors
        else None,
        "limitations": (
            "Assumes a fixed antenna and comparable reflecting water surface. "
            "Datum, antenna phase-centre height and gauge relationship must be "
            "established independently. Arc midpoint and nearest gauge sample "
            "approximate the comparison; correlations, tides during arcs and "
            "vertical land motion are not corrected. Gauge samples can be reused "
            "and matched arcs are not necessarily statistically independent."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if args.plot is not None and accepted:
        plt = importlib.import_module("matplotlib.pyplot")
        figure, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 7))
        axes[0].scatter(
            [row["midpoint_gps_s"] for row in accepted],
            [row["water_level_m"] for row in accepted],
            label="GNSS-IR arcs",
            s=12,
        )
        if gauge:
            axes[0].plot(gauge_times, [row[1] for row in gauge], label="Gauge")
        compared = [row for row in accepted if row["difference_m"] is not None]
        axes[1].scatter(
            [row["midpoint_gps_s"] for row in compared],
            [row["difference_m"] for row in compared],
            s=12,
        )
        axes[0].set_ylabel(f"Water level (m), {args.datum}")
        axes[0].legend()
        axes[1].set_ylabel("GNSS-IR minus gauge (m)")
        axes[1].set_xlabel("GPS seconds")
        figure.tight_layout()
        args.plot.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(args.plot)
        plt.close(figure)
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
