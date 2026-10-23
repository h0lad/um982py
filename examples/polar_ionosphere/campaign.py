"""Compare polar ionosphere reports with independently supplied event windows."""

import argparse
import csv
import json
import math
from collections.abc import Sequence
from pathlib import Path
from statistics import median
from typing import TypedDict

from um982py.field_data import file_sha256


class Event(TypedDict):
    event: str
    start_gps_seconds: float
    end_gps_seconds: float


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        nargs=2,
        action="append",
        required=True,
        metavar=("STATION", "JSON"),
        help="polar_ionosphere report; repeat for stations or days",
    )
    parser.add_argument(
        "--events",
        required=True,
        type=Path,
        help="CSV start_gps_seconds,end_gps_seconds,event",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    inputs = [Path(row[1]) for row in args.report] + [args.events]
    if args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must differ from inputs")
    events: list[Event] = []
    with args.events.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            start, end = float(row["start_gps_seconds"]), float(row["end_gps_seconds"])
            if (
                not math.isfinite(start)
                or not math.isfinite(end)
                or end <= start
                or not row["event"].strip()
            ):
                raise ValueError("events require finite increasing times and a name")
            events.append(
                {
                    "event": row["event"].strip(),
                    "start_gps_seconds": start,
                    "end_gps_seconds": end,
                }
            )
    stations = []
    for name, path in args.report:
        if not name.strip():
            raise ValueError("station label must be non-empty")
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        timeline = report["timeline"]
        summaries = []
        for event in events:
            rows = [
                r
                for r in timeline
                if event["start_gps_seconds"]
                <= float(r["gps_seconds"])
                < event["end_gps_seconds"]
            ]
            roti = [
                float(r["code_roti_tecu_per_min"])
                for r in rows
                if r.get("code_roti_tecu_per_min") is not None
                and math.isfinite(float(r["code_roti_tecu_per_min"]))
            ]
            cn0 = [
                float(r[key])
                for r in rows
                for key in ("cn0_high_dbhz", "cn0_low_dbhz")
                if r.get(key) is not None and math.isfinite(float(r[key]))
            ]
            summaries.append(
                {
                    **event,
                    "dual_frequency_samples": len(rows),
                    "prns": sorted({int(r["prn"]) for r in rows}),
                    "roti_samples": len(roti),
                    "median_code_roti_tecu_per_min": median(roti) if roti else None,
                    "median_cn0_dbhz_both_signals": median(cn0) if cn0 else None,
                }
            )
        stations.append(
            {
                "station": name,
                "source": path,
                "signals_hz": report.get("signals_hz"),
                "tracking_quality": report.get("tracking_quality"),
                "event_windows": summaries,
            }
        )
    result = {
        "stations": stations,
        "inputs": [{"path": str(p), "sha256": file_sha256(p)} for p in inputs],
        "limitations": (
            "Event times and station labels are supplied independently. Temporal "
            "overlap does not establish causation. Code TEC and code ROTI "
            "contain biases, multipath and noise. Median C/N0 combines both "
            "frequencies and is not calibrated signal intensity. Different "
            "stations, frequency pairs and sampling cadences are not "
            "automatically comparable."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return (
        0
        if any(
            window["dual_frequency_samples"]
            for station in stations
            for window in station["event_windows"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
