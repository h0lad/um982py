"""Export GPS ephemerides to a RINEX 3.05 navigation file."""

from collections.abc import Sequence
from pathlib import Path

from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.rinex_nav import export_rinex_navigation


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description="Export GPSEPH as RINEX 3.05 navigation data")
    add_receiver_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=75)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args(argv)
    paths = [
        path
        for path in (args.output, args.replay, args.record, args.json)
        if path is not None
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, output and report paths must be distinct")
    records = capture_records(
        args,
        [Log.GPSEPH],
        duration=args.duration,
        interval=args.interval,
        frames=args.frames,
    )["GPSEPH"]
    if not records:
        parser.error("capture contains no GPSEPH records")
    result = export_rinex_navigation(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.text, encoding="ascii")
    write_json(
        {
            "format": "RINEX 3.05 GPS navigation",
            "messages": result.messages,
            "unknown_fields": result.unknown_fields,
        },
        args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
