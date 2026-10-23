"""Wires capture input for carrier smoothing and divergence reports."""

import sys
from collections.abc import Sequence
from dataclasses import asdict

from um982py.capture import capture_logs
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.experimental.carrier import monitor_divergence, smooth_code
from um982py.measurement import sample_series
from um982py.stats import rms


def carrier_main(name: str, argv: Sequence[str] | None) -> int:
    """Analyse every supported signal on its own phase arcs."""
    parser = experiment_parser(name, "Carrier arc analysis using actual GPS timestamps")
    parser.add_argument("--window", type=int, default=100)
    parser.add_argument(
        "--tau",
        type=float,
        default=100.0,
        help="divergence filter time constant in seconds",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="user divergence rate threshold in m/s",
    )
    parser.add_argument("--max-gap", type=float, default=2.0)
    parser.add_argument("--phase-tolerance", type=float, default=0.5)
    parser.add_argument(
        "--truth-code",
        type=float,
        help="independently known constant pseudorange in metres",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, name)
    if args.truth_code is not None and args.truth_code <= 0:
        parser.error("--truth-code must be a positive pseudorange in metres")
    if min(args.tau, args.max_gap, args.phase_tolerance) <= 0:
        parser.error("tau, maximum gap and phase tolerance must be positive")
    data = capture_logs(
        args,
        [FirmwareLog.RANGE],
        on_progress=progress_printer(name) if args.debug else None,
    )
    groups = sample_series(data["RANGE"])
    result = []
    usable = 0
    for key, samples in groups.items():
        if name == "hatch_smoothing":
            smoothed = smooth_code(
                samples,
                window=args.window,
                max_gap=args.max_gap,
                phase_tolerance=args.phase_tolerance,
            )
            usable += sum(not item.reset for item in smoothed)
            result.append(
                {
                    "signal": asdict(key),
                    "samples": [asdict(item) for item in smoothed],
                    "raw_rmse_m": rms(
                        [sample.code_m - args.truth_code for sample in samples]
                    )
                    if args.truth_code is not None
                    else None,
                    "smoothed_rmse_m": rms(
                        [item.smoothed_m - args.truth_code for item in smoothed]
                    )
                    if args.truth_code is not None
                    else None,
                }
            )
        else:
            divergence = monitor_divergence(
                samples,
                tau=args.tau,
                threshold=args.threshold,
                max_gap=args.max_gap,
                phase_tolerance=args.phase_tolerance,
            )
            usable += sum(not item.reset for item in divergence)
            result.append(
                {
                    "signal": asdict(key),
                    "samples": [asdict(item) for item in divergence],
                }
            )
    print(
        f"Carrier arcs: {usable} usable samples in {len(result)} signals",
        file=sys.stderr,
    )
    write_json(
        {
            "status": "ok" if usable else "insufficient_data",
            "ground_truth": "user-supplied constant pseudorange"
            if args.truth_code is not None
            else "not supplied, leaving filter accuracy unverified",
            "threshold_mps": args.threshold
            if name == "code_carrier_divergence"
            else None,
            "signals": result,
            "next_step": None
            if usable
            else "record two or more locked continuous RANGE epochs",
        },
        args.json,
    )
    return 0 if usable else 1
