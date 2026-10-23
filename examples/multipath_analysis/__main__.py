"""Runs the multipath analysis example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.multipath_analysis import (
    GPS_L1_HZ,
    MultipathSeries,
    Observation,
    epoch_summaries,
    multipath_series,
)
from um982py.capture import GPS_FREQUENCIES, capture_records, gps_signals, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def read_observations(
    record: Record, epoch: float, frequency_hz: float
) -> tuple[Observation, ...]:
    """First observation per satellite of one frame at a single frequency."""
    observations = []
    for item, _ in gps_signals(record, [frequency_hz]):
        prn = item.integer("prn")
        observations.append(
            Observation(
                prn=prn,
                epoch=epoch,
                frequency_hz=frequency_hz,
                pseudorange=item.real("pseudorange"),
                carrier_phase=item.real("carrier_phase"),
            )
        )
    return tuple(observations)


def build_payload(
    series: Sequence[MultipathSeries], frequency_hz: float
) -> dict[str, object]:
    """Serialise the per-signal residuals and the per-epoch summary."""
    return {
        "status": "residuals_estimated" if series else "insufficient_samples",
        "frequency_hz": frequency_hz,
        "series": [
            {
                "prn": item.prn,
                "epochs": len(item.epochs),
                "rms": item.rms,
                "maximum": max((abs(value) for value in item.residuals), default=0.0),
            }
            for item in series
        ],
        "epochs": [
            {
                "epoch": summary.epoch,
                "signals": summary.signals,
                "rms": summary.rms,
                "maximum": summary.maximum,
            }
            for summary in epoch_summaries(series)
        ],
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.multipath_analysis",
        description="Code-minus-carrier multipath from RANGE pseudoranges and phase",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--frequency",
        type=float,
        default=GPS_L1_HZ,
        choices=tuple(GPS_FREQUENCIES.values()),
        help="carrier frequency of the observations in Hz",
    )
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between collected RANGE frames",
    )
    parser.add_argument(
        "--frames", type=int, default=60, help="number of RANGE frames to collect"
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
            f"multipath_analysis debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Run the multipath example against a receiver or a captured transcript."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"multipath_analysis debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.RANGE],
        duration=args.duration,
        frames=args.frames,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )["RANGE"]
    if not records:
        parser.error("capture contains no RANGE records")
    observations = [
        observation
        for index, record in enumerate(records)
        for observation in read_observations(
            record, record_epoch(record), args.frequency
        )
    ]
    series = multipath_series(observations)
    payload = build_payload(series, args.frequency)
    print(
        f"Multipath: {len(series)} signals with residuals in "
        f"{len(records)} RANGE epochs",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
