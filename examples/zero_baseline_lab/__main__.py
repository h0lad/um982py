"""Runs synchronized receiver noise experiments from the command line."""

import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.zero_baseline_lab import double_differences, estimate_noise
from um982py.capture import capture_logs, load_records
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.measurement import sample_series


def main(argv: Sequence[str] | None = None) -> int:
    """Compare two captures made concurrently using a shared antenna."""
    parser = experiment_parser(
        "zero_baseline_lab", "Shared-antenna receiver noise and sigma calibration"
    )
    parser.add_argument(
        "--reference",
        type=Path,
        required=True,
        help="simultaneous second receiver RANGE capture",
    )
    parser.add_argument(
        "--reference-prn",
        type=int,
        required=True,
        help="common continuously locked GPS reference satellite",
    )
    parser.add_argument(
        "--join-tolerance",
        type=float,
        default=0.0,
        help="maximum GPS epoch mismatch in seconds",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "zero_baseline_lab")
    if not 1 <= args.reference_prn <= 32:
        parser.error("--reference-prn must be a GPS PRN in 1..32")
    if args.join_tolerance >= 2:
        parser.error("--join-tolerance must be below the 2-second arc gap")
    data = capture_logs(
        args,
        [FirmwareLog.RANGE],
        on_progress=progress_printer("zero_baseline_lab") if args.debug else None,
    )
    first = sample_series(data["RANGE"])
    second = sample_series(load_records(args.reference, FirmwareLog.RANGE))
    differences = double_differences(
        [sample for series in first.values() for sample in series],
        [sample for series in second.values() for sample in series],
        reference_prn=args.reference_prn,
        tolerance=args.join_tolerance,
    )
    estimates = estimate_noise(differences)
    write_json(
        {
            "status": "ok" if estimates else "insufficient_data",
            "ground_truth": (
                "physical zero baseline supplied by a shared antenna rather than"
                " inferred from positions"
            ),
            "assumption": (
                "DD standard deviation / 2 assumes four equal, "
                "independent observation noises, while shared RF and "
                "reference-satellite correlations remain"
            ),
            "estimates": [asdict(item) for item in estimates],
            "double_differences": [asdict(item) for item in differences],
            "next_step": None
            if estimates
            else (
                "use simultaneous captures with at least three continuous"
                " common epochs and a locked reference PRN"
            ),
        },
        args.json,
    )
    print(
        f"Zero baseline: {len(estimates)} noise estimates from "
        f"{len(differences)} double differences",
        file=sys.stderr,
    )
    return 0 if estimates else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
