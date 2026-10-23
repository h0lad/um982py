"""Runs the elevation optimizer example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence

from examples.elevation_optimizer import (
    SkySatellite,
    brute_force_mask,
    highest_feasible_mask,
    sky_from_satvis_log,
)
from um982py.capture import capture_records, latest_epoch
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def _satellites_from(records: Iterable[Record]) -> tuple[SkySatellite, ...]:
    """Collect the sky positions of already decoded SATVIS2 records."""
    return tuple(
        satellite for record in records for satellite in sky_from_satvis_log(record)
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
    args = parser.parse_args(argv)
    debug_header(args, "elevation_optimizer")
    if args.minimum_satellites < 4:
        parser.error("--minimum-satellites must be at least 4")
    records = capture_records(
        args,
        [FirmwareLog.SATVIS2],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("elevation_optimizer") if args.debug else None,
    )["SATVIS2"]
    satellites = _satellites_from(latest_epoch(records))
    chosen = highest_feasible_mask(
        satellites,
        minimum_satellites=args.minimum_satellites,
        ceiling=args.ceiling,
    )
    scanned = brute_force_mask(
        satellites,
        minimum_satellites=args.minimum_satellites,
        ceiling=args.ceiling,
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
            "chosen": chosen_payload,
            "grid_search": scanned_payload,
        },
        args.json,
    )
    return 0 if chosen is not None else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
