"""Compare simultaneous base and primary-rover observations by native signal."""

import sys
from collections.abc import Sequence
from dataclasses import asdict

from um982py.capture import capture_logs
from um982py.commands import Log
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.messages import Record
from um982py.observation_pairing import pair_base_rover_observations


def _observation(row: Record) -> dict[str, object]:
    return {
        "pseudorange_m": row.real("psr"),
        "adr_cycles_raw": row.real("adr"),
        "cn0_dbhz": row.integer("c_n0") / 100.0,
        "lock_time_s": row.real("locktime"),
        "tracking_status": row.integer("ch_tr_status"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = experiment_parser("base_rover", "Match base and rover observations")
    parser.add_argument("--join-tolerance", type=float, default=0.0)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    if args.antenna not in ("primary", "1") or args.swap_antennas:
        parser.error("this comparison uses the primary rover antenna")
    debug_header(args, "base_rover")
    records = capture_logs(
        args,
        [Log.OBSVBASE, Log.OBSVM],
        on_progress=progress_printer("base_rover") if args.debug else None,
    )
    base, rover = records["OBSVBASE"], records["OBSVM"]
    pairs = pair_base_rover_observations(base, rover, tolerance=args.join_tolerance)
    matches = sum(len(epoch.pairs) for epoch in pairs)
    result = {
        "status": "ok" if matches else "insufficient_data",
        "base_epochs": len(base),
        "rover_epochs": len(rover),
        "paired_epochs": len(pairs),
        "unpaired_base_epochs": len(base) - len(pairs),
        "unpaired_rover_epochs": len(rover) - len(pairs),
        "join_tolerance_s": args.join_tolerance,
        "epochs": [
            {
                "base_gps_seconds": epoch.base_epoch,
                "rover_gps_seconds": epoch.rover_epoch,
                "rover_minus_base_s": epoch.rover_epoch - epoch.base_epoch,
                "base_only_signals": epoch.base_only,
                "rover_only_signals": epoch.rover_only,
                "signals": [
                    {
                        "identity": asdict(pair.identity),
                        "base": _observation(pair.base),
                        "rover": _observation(pair.rover),
                    }
                    for pair in epoch.pairs
                ],
            }
            for epoch in pairs
        ],
        "limitations": (
            "Native status and identifiers are retained without verifying signal "
            "identity or phase alignment. Epoch matching does not prove simultaneous "
            "measurements or correction use. Raw observables include invalid values "
            "when indicated by tracking flags; no double differences are calculated."
        ),
    }
    write_json(result, args.json)
    print(f"Base/rover: {len(pairs)} paired epochs, {matches} signals", file=sys.stderr)
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
