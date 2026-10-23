"""Inspect and validate QZSS disaster reports."""

from collections.abc import Sequence
from dataclasses import asdict

from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.messages.qzss_dcr import decode_qzqsm


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description="Decode QZQSM disaster reports")
    add_receiver_arguments(parser)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--frames", type=int, default=30)
    args = parser.parse_args(argv)
    paths = [path for path in (args.replay, args.record, args.json) if path is not None]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, recording and report paths must be distinct")
    records = capture_records(
        args,
        [Log.QZQSM],
        duration=args.duration,
        interval=args.interval,
        frames=args.frames,
    )["QZQSM"]
    reports = []
    rejected = []
    for record in records:
        try:
            report = decode_qzqsm(record)
        except ValueError as error:
            rejected.append(
                {
                    "satellite_number": record.get("prn"),
                    "payload": record.get("dc_message"),
                    "error": str(error),
                }
            )
            continue
        reports.append(
            {
                **asdict(report),
                "classification": report.classification,
                "category": report.category,
                "information_type": report.weather.information_type
                if report.weather
                else None,
            }
        )
    write_json(
        {
            "status": "ok" if reports else "no_valid_reports",
            "reports": reports,
            "rejected": rejected,
            "limitations": (
                "L1S CRC detects corruption without authenticating the message. "
                "Only version 1 MT43 weather reports are interpreted. "
                "MT44 data are preserved without format-specific decoding. "
                "The signal does not transmit a year."
            ),
        },
        args.json,
    )
    return 0 if reports else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
