"""Runs the RTK quality example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.rtk_quality import (
    EpochSolution,
    QualitySummary,
    summarise,
    timeline,
)
from um982py.capture import capture_records, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages import Record

POSITION_LOGS = (FirmwareLog.BESTPOS, FirmwareLog.RTKPOS)
DIAGNOSTIC_LOGS = (FirmwareLog.RTKDOP, FirmwareLog.BESTSATS, FirmwareLog.RTKSTATUS2)


def _diagnostic_rows(captured: dict[str, tuple[Record, ...]]) -> dict[str, object]:
    """Retain diagnostic epochs and raw fields without joining different logs."""
    return {
        "RTKDOP": [
            {"epoch": record_epoch(row), **dict(row.entries)}
            for row in captured["RTKDOP"]
        ],
        "BESTSATS": [
            {
                "epoch": record_epoch(row),
                "satellites": [
                    dict(item.entries) for item in row.records("satellites")
                ],
            }
            for row in captured["BESTSATS"]
        ],
        "RTKSTATUS2": [
            {"epoch": record_epoch(row), **dict(row.entries)}
            for row in captured["RTKSTATUS2"]
        ],
        "limitation": (
            "Diagnostic records are not matched to solution epochs. BESTSATS "
            "flags and RTKSTATUS2 variant scope remain unverified; 9999 DOP "
            "and zero satellites can indicate unavailable geometry."
        ),
    }


def _epoch_payload(solution: EpochSolution) -> dict[str, object]:
    """Serialise one solution epoch."""
    return {
        "epoch": solution.epoch,
        "position_type": solution.position_type,
        "position_label": solution.position_label,
        "solution_status": solution.solution_status,
        "solution_label": solution.solution_label,
        "fix_class": str(solution.fix_class),
        "available": solution.is_available,
        "fresh_fixed": solution.fresh_fixed,
        "differential_age": solution.differential_age,
        "solution_age": solution.solution_age,
        "satellites_used": solution.satellites_used,
    }


def _summary_payload(summary: QualitySummary) -> dict[str, object]:
    """Serialise the timeline summary."""
    return {
        "epochs": summary.epochs,
        "availability": summary.availability,
        "time_to_first_fix": summary.time_to_first_fix,
        "fresh_fixed_epochs": summary.fresh_fixed_epochs,
        "class_counts": {
            str(fix_class): count for fix_class, count in summary.class_counts.items()
        },
        "mean_differential_age": summary.mean_differential_age,
        "maximum_solution_age": summary.maximum_solution_age,
    }


def _payload(records: Sequence[Record]) -> dict[str, object]:
    """Build the quality payload from the decoded position records."""
    solutions = timeline(records)
    return {
        "epochs": [_epoch_payload(solution) for solution in solutions],
        "summary": None if not solutions else _summary_payload(summarise(solutions)),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.rtk_quality",
        description="RTK fix timeline, correction age and availability.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="also capture firmware RTKDOP, BESTSATS and RTKSTATUS2 logs",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(f"rtk_quality debug: records={counts}", file=sys.stderr, flush=True)

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"rtk_quality debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    position_logs = POSITION_LOGS if args.replay is not None else (FirmwareLog.BESTPOS,)
    logs = (*position_logs, *DIAGNOSTIC_LOGS) if args.diagnostics else position_logs
    captured = capture_records(
        args,
        logs,
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    records = next(
        (captured[log.value] for log in position_logs if captured[log.value]), ()
    )
    if not records:
        parser.error("capture contains no position solution records")
    payload = _payload(records)
    if args.diagnostics:
        payload["receiver_diagnostics"] = _diagnostic_rows(captured)
    summary = payload["summary"]
    if isinstance(summary, dict):
        print(
            f"RTK quality: {summary['epochs']} epochs, availability "
            f"{summary['availability']}; classes {summary['class_counts']}",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
