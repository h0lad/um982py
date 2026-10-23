"""Inspects geometry-free and ionosphere-free three-carrier residuals."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.capture import record_epoch
from um982py.measurement import RangeSample, gnss_range_samples
from um982py.messages import Record
from um982py.signals import tracking_signal

type Trio = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FrequencyClosure:
    """One three-frequency combination with explicit arc and uncertainty metadata."""

    epoch: float
    system: int
    prn: int
    signals: tuple[int, int, int]
    frequencies_hz: Trio
    coefficients: Trio
    independent_equal_noise_gain: float
    arc: int
    arc_start_reason: str | None
    code_closure_m: float
    phase_closure_m: float
    phase_increment_m: float | None
    nominal_phase_sigma_m: float
    threshold_exceeded: bool


def closure_coefficients(frequencies_hz: Trio) -> Trio:
    """Normalize the null vector of geometry and inverse-frequency-squared delay."""
    if any(not math.isfinite(f) or f <= 0 for f in frequencies_hz):
        raise ValueError("three finite positive carrier frequencies are required")
    first, second, third = frequencies_hz
    if len(set(frequencies_hz)) != 3:
        raise ValueError("three distinct carrier frequencies are required")
    ratio2, ratio3 = (first / second) ** 2, (first / third) ** 2
    b = (ratio3 - 1) / (ratio2 - ratio3)
    return 1.0, b, -1.0 - b


def _trios(
    record: Record, *, system: int, signals: tuple[int, int, int], l2c_flag: int
) -> dict[int, tuple[tuple[RangeSample, float], ...]]:
    selected = []
    frequencies: dict[tuple[int, int], float] = {}
    for row in record.records("observations"):
        status = row.integer("tracking_status")
        signal = (status >> 21) & 31
        if (status >> 16) & 7 != system or signal not in signals:
            continue
        if (
            system in (0, 5)
            and signal == 9
            and bool(status & (1 << 26)) != bool(l2c_flag)
        ):
            continue
        channel = row.integer("frequency_channel") - 7 if system == 1 else None
        if channel is not None and not -7 <= channel <= 6:
            continue
        identity = tracking_signal(status, glonass_channel=channel)
        if identity is None or identity.frequency_hz is None:
            continue
        key = row.integer("prn"), signal
        if key in frequencies and frequencies[key] != identity.frequency_hz:
            raise ValueError(
                "conflicting carrier frequencies within one satellite epoch"
            )
        frequencies[key] = identity.frequency_hz
        selected.append(row)
    filtered = Record(record.name, (("observations", tuple(selected)),), record.message)
    samples = gnss_range_samples(filtered)
    by_key = {(sample.key.prn, sample.key.signal): sample for sample in samples}
    return {
        prn: tuple(
            (by_key[prn, signal], frequencies[prn, signal]) for signal in signals
        )
        for prn in sorted({sample.key.prn for sample in samples})
        if all((prn, signal) in by_key for signal in signals)
    }


def frequency_closures(
    records: Sequence[Record],
    *,
    system: int = 0,
    signals: tuple[int, int, int] = (0, 9, 14),
    l2c_flag: int = 1,
    max_gap: float = 2.0,
    threshold_m: float = 0.1,
) -> tuple[FrequencyClosure, ...]:
    """Form same-satellite trios and difference only continuously locked arcs."""
    if (
        not 0 <= system <= 6
        or len(set(signals)) != 3
        or any(not 0 <= s <= 31 for s in signals)
    ):
        raise ValueError("choose a known system and three distinct native signal IDs")
    if l2c_flag not in (0, 1):
        raise ValueError("L2C flag must be zero or one")
    if any(not math.isfinite(v) or v <= 0 for v in (max_gap, threshold_m)):
        raise ValueError("gap and experimental threshold must be finite and positive")
    previous: dict[int, tuple[FrequencyClosure, tuple[float, ...]]] = {}
    output = []
    last_epoch = -math.inf
    for record in records:
        epoch = record_epoch(record)
        if epoch <= last_epoch:
            raise ValueError("RANGE epochs must increase strictly")
        preceding_epoch, last_epoch = last_epoch, epoch
        for prn, trio in _trios(
            record, system=system, signals=signals, l2c_flag=l2c_flag
        ).items():
            frequencies = (trio[0][1], trio[1][1], trio[2][1])
            weights = closure_coefficients(frequencies)
            samples = tuple(item[0] for item in trio)
            code = math.fsum(
                w * s.code_m for w, s in zip(weights, samples, strict=True)
            )
            phase = math.fsum(
                w * s.phase_m for w, s in zip(weights, samples, strict=True)
            )
            old = previous.get(prn)
            reason = "start" if old is None else None
            if old is not None:
                dt = epoch - old[0].epoch
                if dt > max_gap:
                    reason = "gap"
                elif old[0].epoch != preceding_epoch:
                    reason = "missing_trio"
                elif frequencies != old[0].frequencies_hz:
                    reason = "frequency_change"
                elif any(
                    s.lock_seconds < lock + dt - 0.02
                    for s, lock in zip(samples, old[1], strict=True)
                ):
                    reason = "lock_reset"
            increment = (
                phase - old[0].phase_closure_m
                if old is not None and reason is None
                else None
            )
            row = FrequencyClosure(
                epoch,
                system,
                prn,
                signals,
                frequencies,
                weights,
                math.sqrt(sum(w * w for w in weights)),
                (old[0].arc + int(reason is not None)) if old else 1,
                reason,
                code,
                phase,
                increment,
                math.sqrt(
                    sum(
                        (w * s.phase_std_m) ** 2
                        for w, s in zip(weights, samples, strict=True)
                    )
                ),
                increment is not None and abs(increment) > threshold_m,
            )
            previous[prn] = row, tuple(s.lock_seconds for s in samples)
            output.append(row)
    return tuple(output)
