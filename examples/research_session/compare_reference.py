"""Match independent ECEF position CSVs by GPS epoch without interpolation."""

import argparse
import csv
import json
import math
from bisect import bisect_left
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from um982py.field_data import file_sha256


def _read(path: Path) -> list[tuple[float, float, float, float]]:
    with path.open(newline="", encoding="utf-8") as stream:
        result = [
            (
                float(row["gps_seconds"]),
                float(row["x_m"]),
                float(row["y_m"]),
                float(row["z_m"]),
            )
            for row in csv.DictReader(stream)
        ]
    if any(not all(math.isfinite(x) for x in row) for row in result):
        raise ValueError("position epochs and coordinates must be finite")
    if any(b[0] <= a[0] for a, b in pairwise(result)):
        raise ValueError("position epochs must be strictly increasing")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument(
        "--reference-frame",
        required=True,
        help="common frame established independently",
    )
    parser.add_argument("--max-delta-s", type=float, default=0.5)
    parser.add_argument(
        "--same-point",
        action="store_true",
        help="assert both positions refer to the same physical point",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_delta_s) or args.max_delta_s < 0:
        parser.error("matching tolerance must be finite and non-negative")
    if not args.reference_frame.strip():
        parser.error("reference frame must be supplied")
    if args.output.resolve() in (args.observed.resolve(), args.reference.resolve()):
        parser.error("output must differ from inputs")
    observed, reference = _read(args.observed), _read(args.reference)
    times = [item[0] for item in reference]
    matches, unmatched = [], []
    for epoch, x, y, z in observed:
        i = bisect_left(times, epoch)
        candidates = [reference[j] for j in (i - 1, i) if 0 <= j < len(reference)]
        closest = min(candidates, key=lambda row: abs(row[0] - epoch), default=None)
        if closest is None or abs(closest[0] - epoch) > args.max_delta_s:
            unmatched.append(epoch)
            continue
        dx, dy, dz = x - closest[1], y - closest[2], z - closest[3]
        matches.append(
            {
                "observed_gps_seconds": epoch,
                "reference_gps_seconds": closest[0],
                "time_difference_s": epoch - closest[0],
                "ecef_difference_m": [dx, dy, dz],
                "distance_m": math.sqrt(dx * dx + dy * dy + dz * dz),
            }
        )
    result = {
        "frame_supplied_by_user": args.reference_frame,
        "same_point_asserted_by_user": args.same_point,
        "max_delta_s": args.max_delta_s,
        "matches": matches,
        "unmatched_observed_epochs": unmatched,
        "inputs": [
            {"path": str(path), "sha256": file_sha256(path)}
            for path in (args.observed, args.reference)
        ],
        "limitations": (
            "The comparison does not interpolate, transform frames or verify "
            "coordinate epochs and antenna reference points. Matching may "
            "reuse reference epochs."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
