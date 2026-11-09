"""Compute slant TEC, ROT and ROTI from dual-frequency ranges."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples._observation_arcs import CarrierState, continuous
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
from um982py.capture import GPS_FREQUENCIES, gps_signals, record_epoch
from um982py.commands import Log
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
            carrier_state=CarrierState(
                epoch=record_epoch(record),
                frequency_hz=frequency,
                signal=(item.integer("tracking_status") >> 21) & 31,
                lock_seconds=item.real("lock_time"),
                phase_cycles=item.real("carrier_phase"),
                doppler_hz=item.real("doppler"),
            ),
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
    code_by_prn: dict[tuple[int, int], list[TecSample]] = {}
    phase_by_prn: dict[tuple[int, int], list[TecSample]] = {}
    for sample in code_samples:
        code_by_prn.setdefault((sample.prn, sample.arc), []).append(sample)
    for sample in phase_samples:
        phase_by_prn.setdefault((sample.prn, sample.arc), []).append(sample)
    levelled: list[TecSample] = []
    for key in sorted(code_by_prn.keys() & phase_by_prn.keys()):
        codes = sorted(code_by_prn[key], key=lambda sample: sample.epoch)
        phases = sorted(phase_by_prn[key], key=lambda sample: sample.epoch)
        if len(codes) != len(phases) or any(
            code.epoch != phase.epoch for code, phase in zip(codes, phases, strict=True)
        ):
            continue
        values = level_tec(
            [item.tec for item in codes],
            [item.tec for item in phases],
        )
        levelled.extend(
            TecSample(prn=item.prn, epoch=item.epoch, tec=value, arc=item.arc)
            for item, value in zip(codes, values, strict=True)
        )
    return tuple(sorted(levelled, key=lambda item: (item.epoch, item.prn)))


def _continuous_samples(
    epochs: Sequence[tuple[float, Sequence[Observation]]], *, max_gap: float
) -> tuple[list[TecSample], list[TecSample]]:
    """Split each frequency pair when lock, signal or Doppler closure changes."""
    previous: dict[int, tuple[CarrierState, CarrierState]] = {}
    arcs: dict[int, int] = {}
    code_samples: list[TecSample] = []
    phase_samples: list[TecSample] = []
    for epoch, observations in epochs:
        grouped: dict[int, list[Observation]] = {}
        for observation in observations:
            grouped.setdefault(observation.prn, []).append(observation)
        for prn, group in sorted(grouped.items()):
            if len(group) != 2 or group[0].frequency_hz == group[1].frequency_hz:
                previous.pop(prn, None)
                continue
            pair = sorted(group, key=lambda item: item.frequency_hz)
            first, second = pair[0].carrier_state, pair[1].carrier_state
            if first is None or second is None:
                previous.pop(prn, None)
                continue
            states = (first, second)
            if any(
                not math.isfinite(state.lock_seconds) or state.lock_seconds <= 0
                for state in states
            ):
                previous.pop(prn, None)
                continue
            old = previous.get(prn)
            if old is None or not all(
                continuous(before, after, max_gap=max_gap)
                for before, after in zip(old, states, strict=True)
            ):
                arcs[prn] = arcs.get(prn, 0) + 1
            code, phase = slant_tec(pair), phase_tec(pair)
            if (
                code is not None
                and phase is not None
                and math.isfinite(code)
                and math.isfinite(phase)
            ):
                previous[prn] = (states[0], states[1])
                code_samples.append(TecSample(prn, epoch, code, arcs[prn]))
                phase_samples.append(TecSample(prn, epoch, phase, arcs[prn]))
            else:
                previous.pop(prn, None)
    return code_samples, phase_samples


def build_payload(
    samples: Sequence[TecSample],
    prn_count: int,
    frequency_hz: float,
    *,
    phase_samples: Sequence[TecSample] = (),
    max_gap: float | None = None,
) -> dict[str, object]:
    """Collect the TEC, ROT and ROTI series into a JSON payload."""
    rates = rate_of_tec(samples, max_gap=max_gap)
    indexes = roti(rates)
    levelled = _levelled_series(samples, phase_samples) if phase_samples else ()
    phase_rates = rate_of_tec(levelled, max_gap=max_gap)
    phase_indexes = roti(phase_rates)
    return {
        "frequency_hz": frequency_hz,
        "prn_count": prn_count,
        "dual_frequency": bool(samples),
        "limitation": (
            "Code and levelled carrier are uncalibrated TEC proxies; receiver "
            "and satellite differential code biases remain. ROTI requires a "
            "complete continuous five-minute window."
        ),
        "tec": [
            {
                "prn": sample.prn,
                "epoch": sample.epoch,
                "tec": sample.tec,
                "arc": sample.arc,
            }
            for sample in samples
        ],
        "levelled_tec": [
            {
                "prn": sample.prn,
                "epoch": sample.epoch,
                "tec": sample.tec,
                "arc": sample.arc,
            }
            for sample in levelled
        ],
        "rot": [
            {"prn": rate.prn, "epoch": rate.epoch, "rate": rate.rate, "arc": rate.arc}
            for rate in rates
        ],
        "phase_rot": [
            {"prn": rate.prn, "epoch": rate.epoch, "rate": rate.rate, "arc": rate.arc}
            for rate in phase_rates
        ],
        "roti": [
            {
                "prn": index.prn,
                "epoch": index.epoch,
                "index": index.index,
                "arc": index.arc,
            }
            for index in indexes
        ],
        "phase_roti": [
            {
                "prn": index.prn,
                "epoch": index.epoch,
                "index": index.index,
                "arc": index.arc,
            }
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
        [Log.RANGE],
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
    samples, phases = _continuous_samples(epochs, max_gap=2.5 * args.interval)
    prn_count = max((report.prn_count for report in reports), default=0)
    payload = build_payload(
        samples,
        prn_count,
        args.frequency,
        phase_samples=phases,
        max_gap=2.5 * args.interval,
    )
    print(
        f"Ionosphere: {len(samples)} dual-frequency samples from "
        f"{prn_count} PRNs in {len(records)} RANGE epochs",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
