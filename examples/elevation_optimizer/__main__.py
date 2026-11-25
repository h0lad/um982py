# Compare satellite geometry across elevation masks.

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import replace

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records
from examples.elevation_optimizer import (
    SkySatellite,
    brute_force_mask,
    highest_feasible_mask,
    sky_from_satvis_log,
    solution_at,
)
from examples.satellite_monitor import constellation_of
from um982py.capture import latest_epoch
from um982py.commands import Log
from um982py.measurement import gps_epoch
from um982py.messages import Record


def _satellites_from(records: Iterable[Record]) -> tuple[SkySatellite, ...]:
    """Collect the sky positions of already decoded SATVIS2 records."""
    return tuple(
        replace(satellite, system=str(constellation_of(record)))
        for record in records
        for satellite in sky_from_satvis_log(record)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Select the highest elevation mask that keeps the required satellites."""
    parser = ExampleParser(
        prog="python -m examples.elevation_optimizer", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--minimum-satellites", type=int, default=6, help="satellites to keep"
    )
    parser.add_argument(
        "--ceiling", type=float, default=90.0, help="highest mask to consider"
    )
    parser.add_argument(
        "--max-pdop",
        type=float,
        default=6.0,
        help=(
            "maximum acceptable PDOP with one clock per constellation "
            "(default 6; a large value such as 1000 bounds only the satellite count)"
        ),
    )
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "elevation_optimizer")
    if args.minimum_satellites < 4:
        parser.error("--minimum-satellites must be at least 4")
    if args.max_pdop is not None and (
        not math.isfinite(args.max_pdop) or args.max_pdop <= 0
    ):
        parser.error("--max-pdop must be finite and positive")
    records = capture_records(
        args,
        [Log.SATVIS2],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("elevation_optimizer") if args.debug else None,
    )["SATVIS2"]
    frames = latest_epoch(records)
    satellites = _satellites_from(frames)
    max_pdop = args.max_pdop if args.max_pdop is not None else math.inf
    chosen = highest_feasible_mask(
        satellites,
        minimum_satellites=args.minimum_satellites,
        ceiling=args.ceiling,
        max_pdop=max_pdop,
    )
    scanned = brute_force_mask(
        satellites,
        minimum_satellites=args.minimum_satellites,
        ceiling=args.ceiling,
        max_pdop=max_pdop,
    )
    chosen_payload = None if chosen is None else chosen.manifest()
    scanned_payload = None if scanned is None else scanned.manifest()
    if isinstance(chosen_payload, dict):
        print(
            f"Elevation mask: {len(satellites)} satellites, "
            f"chosen {chosen_payload.get('mask')} deg",
            file=sys.stderr,
        )
    write_json(
        {
            "satellites": len(satellites),
            "minimum_satellites": args.minimum_satellites,
            "ceiling": args.ceiling,
            "gps_seconds": gps_epoch(frames[0]) if frames else None,
            "clock_model": "one receiver clock per constellation",
            "maximum_pdop": args.max_pdop,
            "chosen": chosen_payload,
            "grid_search": scanned_payload,
            "mask_sweep": [
                solution.manifest()
                for step in range(math.floor(args.ceiling) + 1)
                if (
                    solution := solution_at(
                        satellites,
                        float(step),
                        minimum_satellites=args.minimum_satellites,
                    )
                )
                is not None
            ],
        },
        args.json,
    )
    return 0 if chosen is not None else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
