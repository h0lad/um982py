"""Explores tracking diagnostic fields from the command line."""

import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.tracking_field_lab import correlate_fields, written_fields
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
from um982py.experimental import FirmwareLog, tracking_slots


def main(argv: Sequence[str] | None = None) -> int:
    """Rank neutral PTOBSINFO fields against external experiment labels."""
    parser = experiment_parser(
        "tracking_field_lab", "Passive PTOBSINFO field hypothesis ranking"
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="independent CSV with epoch,value columns in absolute GPST seconds",
    )
    parser.add_argument("--join-tolerance", type=float, default=0.001)
    parser.add_argument(
        "--selector-field",
        choices=[f"field_{i:02}" for i in range(1, 30)],
        help="filter repeated epochs by a neutral field",
    )
    parser.add_argument("--selector-value", type=float)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "tracking_field_lab")
    if (args.selector_field is None) != (args.selector_value is None):
        parser.error("--selector-field and --selector-value must be supplied together")
    data = capture_logs(
        args,
        [FirmwareLog.PTOBSINFO],
        on_progress=progress_printer("tracking_field_lab") if args.debug else None,
    )
    selected = []
    for record in data["PTOBSINFO"]:
        fields = written_fields(record)
        if args.selector_field is not None and not any(
            field.name == args.selector_field and field.value == args.selector_value
            for field in fields
        ):
            continue
        selected.append((record, fields))
    frames = [(record_epoch(record), fields) for record, fields in selected]
    labels = read_numeric_csv(args.labels, ("epoch", "value")) if args.labels else ()
    if len({row["epoch"] for row in labels}) != len(labels):
        raise ValueError("label epochs must be unique")
    hypotheses = (
        correlate_fields(
            frames,
            {row["epoch"]: row["value"] for row in labels},
            tolerance=args.join_tolerance,
        )
        if labels
        else ()
    )
    usable = any(
        item.correlation is not None and item.pairs >= 5 for item in hypotheses
    )
    write_json(
        {
            "status": "hypotheses_only" if usable else "needs_labels_or_variation",
            "ground_truth": str(args.labels) if args.labels else "not supplied",
            "limitation": (
                "correlation does not establish semantic identification, and no "
                "correlator or ADC interpretation is assigned"
            ),
            "frames": [
                {"epoch": epoch, "fields": [asdict(field) for field in fields]}
                for epoch, fields in frames
            ],
            "slot_coverage": [
                {
                    "epoch": record_epoch(record),
                    "written_slots": [
                        slot.slot for slot in tracking_slots(record) if slot.written
                    ],
                }
                for record, _ in selected
            ],
            "hypotheses": [asdict(item) for item in hypotheses],
        },
        args.json,
    )
    print(
        f"Tracking fields: {len(frames)} frames, {len(hypotheses)} hypotheses",
        file=sys.stderr,
    )
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
