"""Runs the time transfer example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from examples.time_transfer import (
    LEAP_SECONDS,
    day_of_year,
    gpst_from_utc,
    leap_seconds,
    utc_offset_seconds,
)
from um982py.capture import capture_records
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def epoch_from_fields(
    year: float, month: float, day: float, hour: float, minute: float, second: float
) -> datetime:
    """Rebuild a ``TIME`` epoch from its calendar fields, which are UTC."""
    whole = datetime(int(year), int(month), int(day), int(hour), int(minute))
    return whole + timedelta(seconds=second)


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.time_transfer",
        description="GPST and UTC conversion of TIME",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=10.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="TIME output interval in seconds"
    )
    parser.add_argument("--ascii", action="store_true", help="request ASCII TIME")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(f"time_transfer debug: records={counts}", file=sys.stderr, flush=True)

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Convert the first ``TIME`` frame between GPST, UTC and calendar form."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"time_transfer debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.TIME],
        duration=args.duration,
        frames=1,
        interval=args.interval,
        binary=not args.ascii,
        on_progress=_progress_callback() if args.debug else None,
    )["TIME"]
    if not records:
        parser.error("capture contains no TIME record")
    record = records[0]
    if record.real("year") < 1980 or record["utc_status"] not in (1, "VALID"):
        write_json(
            {"status": "insufficient_data", "reason": "receiver UTC is not valid"},
            args.json,
        )
        return 1
    utc = epoch_from_fields(
        record.real("year"),
        record.real("month"),
        record.real("day"),
        record.real("hour"),
        record.real("minute"),
        record.real("millisecond") / 1000.0,
    )
    gpst = gpst_from_utc(utc)
    reported = record.real("utc_offset")
    table_offset = utc_offset_seconds(gpst)
    print(f"gpst {gpst.isoformat()} utc {utc.isoformat()}")
    print(f"day of year {day_of_year(utc.date())} leap seconds {leap_seconds(utc)}")
    print(f"receiver utc_offset {reported:+.0f} s table {table_offset:+.0f} s")
    print(
        f"Time transfer: {utc.isoformat()} UTC, leap seconds {leap_seconds(utc)}, "
        f"receiver offset {reported:+.0f} s vs table {table_offset:+.0f} s",
        file=sys.stderr,
    )
    payload = {
        "gpst": gpst.isoformat(),
        "utc": utc.isoformat(),
        "leap_seconds": leap_seconds(utc),
        "utc_offset_seconds": table_offset,
        "receiver_utc_offset": reported,
        "day_of_year": day_of_year(utc.date()),
        "leap_table": [
            {"effective": entry.effective.isoformat(), "seconds": entry.total_seconds}
            for entry in LEAP_SECONDS
        ],
    }
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
