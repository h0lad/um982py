"""Compare signal and elevation-bin summaries across two field captures."""

import argparse
import csv
import json
import math
from collections.abc import Sequence
from pathlib import Path

from um982py.field_data import file_sha256

_KEYS = ("system", "signal", "l2c_flag", "elevation_min_deg", "elevation_max_deg")


def _load(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in _KEYS)
        if key in result:
            raise ValueError("duplicate signal/elevation bin")
        if not math.isfinite(float(row["median_difference_db"])):
            raise ValueError("median differences must be finite")
        result[key] = row
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--earlier", type=Path, required=True)
    parser.add_argument("--later", type=Path, required=True)
    parser.add_argument("--earlier-note", required=True)
    parser.add_argument("--later-note", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() in (args.earlier.resolve(), args.later.resolve()):
        parser.error("output must differ from inputs")
    first, second = _load(args.earlier), _load(args.later)
    rows = []
    for key in sorted(first.keys() & second.keys()):
        a, b = first[key], second[key]
        rows.append(
            {
                **dict(zip(_KEYS, key, strict=True)),
                "earlier_median_db": float(a["median_difference_db"]),
                "later_median_db": float(b["median_difference_db"]),
                "change_db": float(b["median_difference_db"])
                - float(a["median_difference_db"]),
                "earlier_satellites": int(a["satellites"]),
                "later_satellites": int(b["satellites"]),
            }
        )
    report = {
        "earlier_note": args.earlier_note,
        "later_note": args.later_note,
        "matched_bins": rows,
        "unmatched_earlier": [list(k) for k in sorted(first.keys() - second.keys())],
        "unmatched_later": [list(k) for k in sorted(second.keys() - first.keys())],
        "inputs": [
            {"path": str(p), "sha256": file_sha256(p)}
            for p in (args.earlier, args.later)
        ],
        "limitations": (
            "Signal/elevation bins do not establish matched satellites, azimuths "
            "or reflecting surfaces. Check antenna roles, setup, sky geometry "
            "and field conditions independently."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
