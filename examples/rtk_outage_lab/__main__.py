"""Simulates independently timed correction outages from the command line."""

import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.rtk_outage_lab import (
    Outage,
    PositionEpoch,
    analyse_outages,
    epoch_timeline,
    summarize_outages,
)
from examples.rtk_quality import FixClass, solution_from_record
from um982py.capture import capture_logs, record_epoch
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    read_numeric_csv,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog


def main(argv: Sequence[str] | None = None) -> int:
    """Score real receiver recovery using a correction-link event CSV."""
    parser = experiment_parser(
        "rtk_outage_lab", "RTK outage impact and sustained fix recovery"
    )
    parser.add_argument(
        "--outages",
        type=Path,
        required=True,
        help="independent start,end absolute GPST event CSV",
    )
    parser.add_argument(
        "--truth-ecef",
        type=float,
        nargs=3,
        help="surveyed static antenna X Y Z in metres",
    )
    parser.add_argument("--sustained-seconds", type=float, default=3.0)
    parser.add_argument("--max-gap", type=float, default=2.0)
    parser.add_argument("--timeline-csv", type=Path)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "rtk_outage_lab")
    events = read_numeric_csv(args.outages, ("start", "end"))
    data = capture_logs(
        args,
        [FirmwareLog.BESTXYZ],
        on_progress=progress_printer("rtk_outage_lab") if args.debug else None,
    )
    epochs = []
    for record in data["BESTXYZ"]:
        time = record_epoch(record)
        quality = solution_from_record(time, record)
        epochs.append(
            PositionEpoch(
                time,
                (record.real("p_x"), record.real("p_y"), record.real("p_z")),
                quality.is_available,
                quality.fix_class is FixClass.FIXED,
                quality.differential_age,
            )
        )
    truth = tuple(args.truth_ecef) if args.truth_ecef is not None else None
    results = analyse_outages(
        epochs,
        [Outage(row["start"], row["end"]) for row in events],
        truth=None if truth is None else (truth[0], truth[1], truth[2]),
        sustained_seconds=args.sustained_seconds,
        max_gap=args.max_gap,
    )
    timeline = epoch_timeline(epochs, truth)
    if args.timeline_csv is not None:
        args.timeline_csv.parent.mkdir(parents=True, exist_ok=True)
        rows = ["gps_epoch,computed,fixed,correction_age_s,truth_error_m\n"]
        for item in timeline:
            error = item.truth_error_m
            rows.append(
                f"{item.gps_epoch:.3f},{int(item.computed)},"
                f"{int(item.fixed)},{item.correction_age_s:.3f},"
                + ("" if error is None else f"{error:.4f}")
                + "\n"
            )
        args.timeline_csv.write_text(
            "".join(rows),
            encoding="ascii",
        )
    write_json(
        {
            "ground_truth": {
                "link_events": str(args.outages),
                "position": "surveyed ECEF supplied by user"
                if truth
                else "not supplied; steps are continuity metrics",
            },
            "status": "ok",
            "summary": asdict(summarize_outages(results)),
            "outages": [asdict(item) for item in results],
            "timeline": [asdict(item) for item in timeline],
        },
        args.json,
    )
    print(
        f"RTK outages: {len(results)} analysed events from {len(epochs)} epochs",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
