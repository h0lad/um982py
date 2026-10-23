"""Collect RANGE frames and report per-signal quality."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.signal_quality_report import (
    SignalObservation,
    as_dict,
    observations_from_record,
    summarise,
)
from um982py.capture import capture_records
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def _payload(records: Sequence[Record]) -> dict[str, object]:
    """Build the signal quality payload from the decoded RANGE records."""
    per_epoch = [observations_from_record(record) for record in records]
    observations = [observation for epoch in per_epoch for observation in epoch]
    return {
        "epochs": [as_dict(summarise(epoch)) for epoch in per_epoch if epoch],
        "observation_count": len(observations),
        "per_channel_observation_count": _channel_totals(observations),
    }


def _channel_totals(
    observations: Sequence[SignalObservation],
) -> dict[str, int]:
    """Count observations per frequency channel over the whole capture."""
    totals: dict[int, int] = {}
    for observation in observations:
        channel = observation.frequency_channel
        totals[channel] = totals.get(channel, 0) + 1
    return {str(channel): count for channel, count in sorted(totals.items())}


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.signal_quality_report",
        description="Per-signal C/N0, lock time and tracking status from RANGE.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="RANGE output interval in seconds"
    )
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
        print(
            f"signal_quality_report debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Collect RANGE frames and report per-signal C/N0 and lock time."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"signal_quality_report debug: {origin}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.RANGE],
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )["RANGE"]
    if not records:
        parser.error("capture contains no RANGE records")
    payload = _payload(records)
    print(
        f"Signal quality: {payload['observation_count']} observations in "
        f"{len(records)} RANGE epochs",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
