"""Compare accepted GNSS-IR arcs with a measured snow-free reflector height."""

import argparse
import csv
import json
import math
from collections.abc import Sequence
from pathlib import Path

from um982py.field_data import file_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arcs", type=Path, nargs="+", required=True, help="GNSS-IR --csv files"
    )
    parser.add_argument("--antenna", choices=("ANT1", "ANT2"), required=True)
    parser.add_argument(
        "--baseline-height-m",
        type=float,
        required=True,
        help="measured snow-free antenna-to-surface height",
    )
    parser.add_argument("--field", type=Path, help="CSV with gps_seconds,snow_depth_m")
    parser.add_argument("--field-window-s", type=float, default=3600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.baseline_height_m)
        or args.baseline_height_m <= 0
        or not math.isfinite(args.field_window_s)
        or args.field_window_s < 0
    ):
        parser.error("baseline must be positive and match window non-negative")
    inputs = [*args.arcs, *([args.field] if args.field else [])]
    if args.output.resolve() in {item.resolve() for item in inputs}:
        parser.error("output must differ from all inputs")
    reference: list[tuple[float, float]] = []
    if args.field:
        with args.field.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                epoch, depth = float(row["gps_seconds"]), float(row["snow_depth_m"])
                if not math.isfinite(epoch) or not math.isfinite(depth) or depth < 0:
                    raise ValueError(
                        "field epochs and non-negative depths must be finite"
                    )
                reference.append((epoch, depth))
    rows = []
    rejected = []
    for path in args.arcs:
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row["antenna"] != args.antenna:
                    continue
                if row["rejection"]:
                    rejected.append({"source": str(path), **row})
                    continue
                height = float(row["height_m"])
                start, end = float(row["start_gps_s"]), float(row["end_gps_s"])
                if (
                    not all(math.isfinite(v) for v in (height, start, end))
                    or height <= 0
                    or end < start
                ):
                    raise ValueError("accepted arc has invalid height or epoch")
                resolution = (
                    float(row["height_resolution_m"])
                    if row["height_resolution_m"]
                    else None
                )
                if resolution is not None and (
                    not math.isfinite(resolution) or resolution < 0
                ):
                    raise ValueError("invalid spectral height resolution")
                epoch = (start + end) / 2
                nearest = min(reference, key=lambda r: abs(r[0] - epoch), default=None)
                match = (
                    nearest
                    if nearest and abs(nearest[0] - epoch) <= args.field_window_s
                    else None
                )
                proxy = args.baseline_height_m - height
                rows.append(
                    {
                        "source": str(path),
                        "antenna": args.antenna,
                        "system": row["system"],
                        "prn": row["prn"],
                        "signal": row["signal"],
                        "direction": row["direction"],
                        "start_gps_s": start,
                        "end_gps_s": end,
                        "height_m": height,
                        "snow_height_proxy_m": proxy,
                        "height_resolution_m": resolution,
                        "field_epoch_gps_s": match[0] if match else None,
                        "field_depth_m": match[1] if match else None,
                        "proxy_minus_field_m": proxy - match[1] if match else None,
                    }
                )
    result = {
        "baseline_height_m": args.baseline_height_m,
        "antenna": args.antenna,
        "field_window_s": args.field_window_s,
        "inputs": [{"path": str(path), "sha256": file_sha256(path)} for path in inputs],
        "accepted_arcs": sorted(rows, key=lambda r: float(r["start_gps_s"])),
        "rejected_arcs": rejected,
        "limitations": (
            "The proxy assumes a fixed antenna and comparable reflecting surface, and "
            "spectral resolution is not uncertainty. Negative proxies are retained."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
