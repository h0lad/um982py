"""Inspect three-frequency residuals without ephemerides or external corrections."""

import sys
from collections.abc import Sequence
from dataclasses import asdict

from examples.triple_frequency_closure import frequency_closures
from um982py.capture import capture_logs
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.diagnostics import signal_inventory
from um982py.experimental import FirmwareLog


def main(argv: Sequence[str] | None = None) -> int:
    """Capture one antenna and report geometry and ionosphere cancelling residuals."""
    parser = experiment_parser(
        "triple_frequency_closure", "Three-frequency closure laboratory"
    )
    parser.add_argument("--system", type=int, choices=range(7), default=0)
    parser.add_argument(
        "--signals", type=int, nargs=3, default=(0, 9, 14), metavar="ID"
    )
    parser.add_argument("--l2c-flag", type=int, choices=(0, 1), default=1)
    parser.add_argument("--max-gap", type=float, default=2.0)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.1,
        help="experimental phase-increment threshold, m",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "triple_frequency_closure")
    if len(set(args.signals)) != 3 or any(
        not 0 <= value <= 31 for value in args.signals
    ):
        parser.error("--signals needs three distinct native IDs in 0..31")
    data = capture_logs(
        args,
        [FirmwareLog.RANGE],
        on_progress=progress_printer("triple_frequency_closure")
        if args.debug
        else None,
    )
    rows = frequency_closures(
        data["RANGE"],
        system=args.system,
        signals=(args.signals[0], args.signals[1], args.signals[2]),
        l2c_flag=args.l2c_flag,
        max_gap=args.max_gap,
        threshold_m=args.threshold,
    )
    increments = sum(row.phase_increment_m is not None for row in rows)
    write_json(
        {
            "status": "ok" if increments else "insufficient_continuous_trios",
            "antenna": args.antenna,
            "system": args.system,
            "signals": args.signals,
            "l2c_flag": args.l2c_flag,
            "range_epochs": len(data["RANGE"]),
            "signal_inventory": [
                item
                for item in signal_inventory(data["RANGE"])
                if item["system"] == args.system and item["signal"] in args.signals
            ],
            "next_step": None
            if increments
            else (
                "Check the requested signal IDs, code-and-phase validity and L2C "
                "flag in signal_inventory. Three distinct carriers must be present "
                "on the selected antenna for at least two continuous epochs. Set "
                "--max-gap to match the capture cadence."
            ),
            "tested_increments": increments,
            "threshold_m": args.threshold,
            "threshold_exceedances": sum(row.threshold_exceeded for row in rows),
            "limitation": (
                "Not a unique cycle-slip detector or an ionospheric measurement. "
                "Hardware biases, multipath, antenna phase centres, higher-order "
                "ionosphere and amplified noise remain. Absolute phase includes "
                "ambiguities. Nominal sigma assumes independent receiver-reported "
                "phase errors and is not a calibrated uncertainty. No L2C M/L "
                "component is inferred from bit 26."
            ),
            "rows": [asdict(row) for row in rows],
        },
        args.json,
    )
    print(
        f"Triple-frequency closure: {increments} increments, "
        f"{sum(row.threshold_exceeded for row in rows)} threshold exceedances "
        f"in {len(data['RANGE'])} RANGE epochs",
        file=sys.stderr,
    )
    return 0 if increments else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
