"""Runs the scintillation monitor example from the command line."""

from __future__ import annotations

import math
import sys
from collections import Counter
from collections.abc import Callable, Sequence

from examples.scintillation_monitor import (
    ScintillationSample,
    ScintillationSummary,
    summarise,
    unambiguous_samples,
)
from um982py.capture import capture_records, uniform_interval
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.geodesy import records_from
from um982py.messages.record import Record


def samples_of_frame(record: Record) -> list[ScintillationSample]:
    """One sample per tracked signal of a ``RANGE`` frame."""
    return [
        ScintillationSample(
            prn=(
                f"{(observation.integer('tracking_status') >> 16) & 7}:"
                f"{observation.integer('prn')}:"
                f"{(observation.integer('tracking_status') >> 21) & 31}"
            ),
            frequency_channel=int(observation.real("frequency_channel")),
            cn0_db_hz=observation.real("cn0"),
        )
        for observation in records_from(record, "observations")
        if observation.integer("tracking_status") & (1 << 12)
        and math.isfinite(observation.real("cn0"))
        and observation.real("cn0") > 0
    ]


def payload_of(summary: ScintillationSummary) -> dict[str, object]:
    """Serialisable view of one signal summary."""
    return {
        "prn": summary.prn,
        "frequency_channel": summary.frequency_channel,
        "sample_count": summary.sample_count,
        "status": "estimated" if summary.sample_count >= 2 else "insufficient_samples",
        "mean_cn0_db_hz": summary.mean_cn0_db_hz,
        "s4": summary.s4,
        "observable": "uncalibrated_cn0_variability_proxy",
        "limitation": (
            "RANGE C/N0 is receiver-filtered and not calibrated signal intensity, "
            "and no detrending or thermal-noise correction is applied. This does not "
            "establish ionospheric scintillation. S4-rate is not TEC ROTI."
        ),
        "s4_rate_std_per_second": summary.roti_proxy,
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.scintillation_monitor",
        description="RANGE C/N0 scintillation monitor",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument("--window", type=int, default=60, help="epochs per S4 window")
    parser.add_argument("--interval", type=float, default=1.0, help="epoch seconds")
    parser.add_argument(
        "--frames", type=int, default=120, help="RANGE epochs to collect"
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
            f"scintillation_monitor debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Report the S4 scintillation index of every signal in ``RANGE``."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"scintillation_monitor debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    if args.window < 2:
        parser.error("--window must be at least 2")
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
    frames = [samples_of_frame(record) for record in records]
    samples = unambiguous_samples(frames)
    counts = Counter((sample.prn, sample.frequency_channel) for sample in samples)
    samples = [
        sample
        for sample in samples
        if counts[sample.prn, sample.frequency_channel] == len(frames)
    ]
    summaries = summarise(
        samples,
        window=args.window,
        interval_seconds=uniform_interval(records, args.interval),
    )
    observations = sum(len(frame) for frame in frames)
    print(
        f"Scintillation: {len(records)} epochs, {observations} observations, "
        f"{len(summaries)} signals",
        file=sys.stderr,
    )
    print(f"epochs {len(records)} observations {observations} signals {len(summaries)}")
    for summary in summaries:
        print(
            f"  prn {summary.prn:>3} ch {summary.frequency_channel:>2}"
            f"  cn0 {summary.mean_cn0_db_hz:6.2f} dB-Hz"
            f"  s4 proxy {summary.s4:.3f}  s4-rate std {summary.roti_proxy:.4f} per s"
        )
    write_json([payload_of(summary) for summary in summaries], args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
