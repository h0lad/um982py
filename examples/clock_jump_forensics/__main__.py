"""Flags receiver clock discontinuities from the command line."""

import sys
from collections.abc import Sequence
from dataclasses import asdict
from itertools import pairwise

from examples.clock_jump_forensics import clock_residuals, detect_clock_jumps
from um982py.capture import capture_logs
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.measurement import range_samples


def main(argv: Sequence[str] | None = None) -> int:
    """Report common jumps without labelling them independent timing accuracy."""
    parser = experiment_parser(
        "clock_jump_forensics", "Common-mode code and carrier jump candidates"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1000.0,
        help="minimum common range jump in metres",
    )
    parser.add_argument(
        "--agreement", type=float, default=10.0, help="consensus half-width in metres"
    )
    parser.add_argument("--max-gap", type=float, default=2.0)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "clock_jump_forensics")
    data = capture_logs(
        args,
        [FirmwareLog.RANGE],
        on_progress=progress_printer("clock_jump_forensics") if args.debug else None,
    )
    epochs = [
        tuple(sample for sample in range_samples(record) if sample.key.signal == 0)
        for record in data["RANGE"]
    ]
    events = [
        event
        for before, after in pairwise(epochs)
        if (
            event := detect_clock_jumps(
                before,
                after,
                threshold_m=args.threshold,
                agreement_m=args.agreement,
                max_gap=args.max_gap,
            )
        )
        is not None
    ]
    usable = sum(
        len(clock_residuals(before, after, max_gap=args.max_gap)[0]) >= 4
        for before, after in pairwise(epochs)
    )
    write_json(
        {
            "status": "ok" if usable else "insufficient_data",
            "tested_intervals": usable,
            "ground_truth": (
                "Ground truth is not supplied. Attribution of common-mode "
                "candidates requires independent timing evidence."
            ),
            "events": [asdict(event) for event in events],
            "next_step": None
            if usable
            else (
                "record at least two epochs with four continuously locked"
                " GPS L1 satellites"
            ),
        },
        args.json,
    )
    print(
        f"Clock jumps: {len(events)} events in {usable} tested intervals",
        file=sys.stderr,
    )
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
