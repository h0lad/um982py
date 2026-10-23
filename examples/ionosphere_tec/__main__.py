"""Runs the ionosphere TEC example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.ionosphere_tec import (
    GPS_L1_HZ,
    Observation,
    TecSample,
    level_tec,
    phase_tec,
    rate_of_tec,
    roti,
    slant_tec,
    tec_report,
)
from um982py.capture import GPS_FREQUENCIES, capture_records, gps_signals, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def read_observations(
    record: Record, frequency_hz: float, secondary_frequency_hz: float = 1176.45e6
) -> tuple[Observation, ...]:
    """GPS observations at their actual selected carrier frequencies."""
    return tuple(
        Observation(
            prn=item.integer("prn"),
            frequency_hz=frequency,
            pseudorange=item.real("pseudorange"),
            carrier_phase=item.real("carrier_phase"),
        )
        for item, frequency in gps_signals(
            record, [frequency_hz, secondary_frequency_hz]
        )
    )


def _levelled_series(
    code_samples: Sequence[TecSample],
    phase_samples: Sequence[TecSample],
) -> tuple[TecSample, ...]:
    """Level carrier-phase TEC to code TEC independently for each satellite."""
    code_by_prn: dict[int, list[TecSample]] = {}
    phase_by_prn: dict[int, list[TecSample]] = {}
    for sample in code_samples:
        code_by_prn.setdefault(sample.prn, []).append(sample)
    for sample in phase_samples:
        phase_by_prn.setdefault(sample.prn, []).append(sample)
    levelled: list[TecSample] = []
    for prn in sorted(code_by_prn.keys() & phase_by_prn.keys()):
        codes = code_by_prn[prn]
        phases = phase_by_prn[prn]
        if len(codes) != len(phases):
            continue
        values = level_tec(
            [item.tec for item in codes],
            [item.tec for item in phases],
        )
        levelled.extend(
            TecSample(prn=prn, epoch=item.epoch, tec=value)
            for item, value in zip(codes, values, strict=True)
        )
    return tuple(sorted(levelled, key=lambda item: (item.epoch, item.prn)))


def _phase_samples(
    observations: Sequence[Observation], epoch: float
) -> tuple[TecSample, ...]:
    """Carrier-phase TEC of every paired satellite at one epoch."""
    by_prn: dict[int, list[Observation]] = {}
    for observation in observations:
        by_prn.setdefault(observation.prn, []).append(observation)
    samples = []
    for prn, group in sorted(by_prn.items()):
        code = slant_tec(group)
        carrier = phase_tec(group)
        if code is not None and carrier is not None:
            samples.append(TecSample(prn=prn, epoch=epoch, tec=carrier))
    return tuple(samples)


def build_payload(
    samples: Sequence[TecSample],
    prn_count: int,
    frequency_hz: float,
    *,
    phase_samples: Sequence[TecSample] = (),
) -> dict[str, object]:
    """Collect the TEC, ROT and ROTI series into a JSON payload."""
    rates = rate_of_tec(samples)
    indexes = roti(rates)
    levelled = _levelled_series(samples, phase_samples) if phase_samples else ()
    phase_rates = rate_of_tec(levelled)
    phase_indexes = roti(phase_rates)
    return {
        "frequency_hz": frequency_hz,
        "prn_count": prn_count,
        "dual_frequency": bool(samples),
        "tec": [
            {"prn": sample.prn, "epoch": sample.epoch, "tec": sample.tec}
            for sample in samples
        ],
        "levelled_tec": [
            {"prn": sample.prn, "epoch": sample.epoch, "tec": sample.tec}
            for sample in levelled
        ],
        "rot": [
            {"prn": rate.prn, "epoch": rate.epoch, "rate": rate.rate} for rate in rates
        ],
        "phase_rot": [
            {"prn": rate.prn, "epoch": rate.epoch, "rate": rate.rate}
            for rate in phase_rates
        ],
        "roti": [
            {"prn": index.prn, "epoch": index.epoch, "index": index.index}
            for index in indexes
        ],
        "phase_roti": [
            {"prn": index.prn, "epoch": index.epoch, "index": index.index}
            for index in phase_indexes
        ],
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.ionosphere_tec",
        description="Slant TEC, ROT and ROTI from geometry-free RANGE observations",
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
        "--secondary-frequency",
        type=float,
        default=None,
        choices=tuple(GPS_FREQUENCIES.values()),
        help="second GPS carrier in Hz, defaulting to L5 on ANT1 and L2 on ANT2",
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
        print(f"ionosphere_tec debug: records={counts}", file=sys.stderr, flush=True)

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Run the TEC example against a receiver or a captured transcript."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"ionosphere_tec debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    if args.secondary_frequency is None:
        args.secondary_frequency = (
            1227.60e6 if args.antenna in ("secondary", "2") else 1176.45e6
        )
    if args.frequency == args.secondary_frequency:
        parser.error("choose two different GPS carrier frequencies")
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
    epochs = [
        (
            record_epoch(record),
            read_observations(record, args.frequency, args.secondary_frequency),
        )
        for record in records
    ]
    reports = [tec_report(obs, epoch) for epoch, obs in epochs]
    phases = [sample for epoch, obs in epochs for sample in _phase_samples(obs, epoch)]
    samples = [sample for report in reports for sample in report.samples]
    prn_count = max((report.prn_count for report in reports), default=0)
    payload = build_payload(samples, prn_count, args.frequency, phase_samples=phases)
    print(
        f"Ionosphere: {len(samples)} dual-frequency samples from "
        f"{prn_count} PRNs in {len(records)} RANGE epochs",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
