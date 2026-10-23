"""Collect dual-antenna baselines and report heading and pitch."""

from __future__ import annotations

import itertools
import sys
from collections.abc import Callable, Sequence

from examples.heading_attitude import (
    Attitude,
    angular_rate,
    attitude_from_record,
    swapped_attitude,
)
from um982py.capture import capture_records, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def _attitude_payload(attitude: Attitude) -> dict[str, object]:
    """Serialise one attitude."""
    return {
        "heading": attitude.heading,
        "pitch": attitude.pitch,
        "baseline_length": attitude.baseline_length,
    }


def _attitude(record: Record, *, swapped: bool) -> Attitude:
    """Attitude of one baseline record, with the antenna roles applied."""
    attitude = attitude_from_record(record)
    return swapped_attitude(attitude) if swapped else attitude


def _payload(records: Sequence[Record], *, swapped: bool = False) -> dict[str, object]:
    """Build the attitude payload from the decoded baselines."""
    attitudes = [
        {
            **_attitude_payload(_attitude(record, swapped=swapped)),
            "solution_status": record.get("p_sol_status"),
            "position_type": record.get("pos_type"),
        }
        for record in records
    ]
    rates = []
    for first, second in itertools.pairwise(records):
        interval = record_epoch(second) - record_epoch(first)
        if interval <= 0:
            continue
        rate = angular_rate(
            _attitude(first, swapped=swapped),
            _attitude(second, swapped=swapped),
            interval,
        )
        rates.append(
            {
                "epoch": record_epoch(second),
                "interval_seconds": interval,
                "rate_degrees_per_second": rate,
            }
        )
    return {
        "baselines": len(attitudes),
        "latest": None if not attitudes else attitudes[-1],
        "history": attitudes,
        "angular_rates": rates,
        "latest_rate_degrees_per_second": (
            None if not rates else rates[-1]["rate_degrees_per_second"]
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.heading_attitude",
        description="Heading and pitch of the dual-antenna baseline.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="baseline output interval in seconds",
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
            f"heading_attitude debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Collect baselines, then report heading, pitch and angular rates."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"heading_attitude debug: {origin}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.BSLNENUHD],
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )["BSLNENUHD"]
    if not records:
        parser.error(
            "no BSLNENUHD baseline; a working dual-antenna solution is required"
        )
    payload = _payload(records, swapped=args.swap_antennas)
    latest = payload["latest"]
    if isinstance(latest, dict):
        print(
            f"Heading: {latest['heading']}; pitch {latest['pitch']}; "
            f"baseline {latest['baseline_length']} m "
            f"({payload['baselines']} baselines)",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
