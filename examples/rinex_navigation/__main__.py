"""Export receiver ephemerides to a RINEX 3.05 navigation file."""

from collections.abc import Sequence
from pathlib import Path

from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.rinex_nav import export_rinex_navigation


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        description="Export ephemerides as RINEX 3.05 navigation data"
    )
    add_receiver_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=75)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument(
        "--systems", nargs="+", choices=("GPS", "GAL", "BDS"), default=["GPS"]
    )
    parser.add_argument("--bdseph-time-scale", choices=("BDT", "GPST"))
    args = parser.parse_args(argv)
    if "BDS" in args.systems and args.bdseph_time_scale is None:
        parser.error("--bdseph-time-scale is required for BDS")
    paths = [
        path
        for path in (args.output, args.replay, args.record, args.json)
        if path is not None
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, output and report paths must be distinct")
    selected = [
        log
        for name, log in (("GPS", Log.GPSEPH), ("GAL", Log.GALEPH), ("BDS", Log.BDSEPH))
        if name in args.systems
    ]
    captured = capture_records(
        args,
        selected,
        duration=args.duration,
        interval=args.interval,
        frames=args.frames,
    )
    records = [record for log in selected for record in captured[log.value]]
    if not records:
        parser.error("capture contains no selected ephemeris records")
    result = export_rinex_navigation(records, bdseph_time_scale=args.bdseph_time_scale)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.text, encoding="ascii")
    write_json(
        {
            "format": "RINEX 3.05 navigation",
            "messages": result.messages,
            "unknown_fields": result.unknown_fields,
        },
        args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
