# Map same-epoch GGA positions and GST precision as GeoJSON.

from collections.abc import Sequence
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.position_precision import map_precision
from um982py import Log


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_output_interval(default=1.0)
    parser.add_argument(
        "--reference-frame",
        choices=("WGS84",),
        required=True,
        help="confirm the receiver positions use WGS84",
    )
    parser.add_argument("--geojson", type=Path, help="write mapped positions here")
    parser.add_argument(
        "--max-records",
        type=int,
        default=10_000,
        help="maximum combined GGA and GST records from a single session",
    )
    args = parser.parse_args(argv)
    if args.max_records < 1:
        parser.error("--max-records must be positive")
    data = capture_records(
        args, [Log.GPGGA, Log.GPGST], duration=args.duration, interval=args.interval
    )
    report = map_precision(data["GPGGA"], data["GPGST"], max_records=args.max_records)
    if args.geojson is not None:
        write_json(report["geojson"], args.geojson)
    write_json(report, args.json)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
