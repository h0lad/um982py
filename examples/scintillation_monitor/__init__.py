"""Computes an uncalibrated S4-like variability proxy from receiver C/N0."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from um982py.stats import mean, stddev

__all__ = [
    "LockLossEpoch",
    "ScintillationEpoch",
    "ScintillationSample",
    "ScintillationSummary",
    "attribute_lock_loss",
    "linear_power",
    "roti_proxy",
    "s4_index",
    "sliding_s4",
    "summarise",
    "unambiguous_samples",
]


@dataclass(frozen=True, slots=True)
class ScintillationSample:
    """One C/N0 observation in dB-Hz of a PRN and frequency channel."""

    prn: str
    frequency_channel: int
    cn0_db_hz: float


@dataclass(frozen=True, slots=True)
class ScintillationSummary:
    """S4 index and rate proxy of one signal over its last window."""

    prn: str
    frequency_channel: int
    sample_count: int
    mean_cn0_db_hz: float
    s4: float
    roti_proxy: float


@dataclass(frozen=True, slots=True)
class ScintillationEpoch:
    """S4 index of one epoch and the tracking slots the receiver had written."""

    epoch: float
    s4: float
    written_slots: int


@dataclass(frozen=True, slots=True)
class LockLossEpoch:
    """One epoch whose scintillation and channel occupancy disagree."""

    epoch: float
    s4: float
    written_slots: int
    attribution: str


def attribute_lock_loss(
    epochs: Sequence[ScintillationEpoch],
    *,
    s4_threshold: float = 0.6,
    minimum_slots: int = 1,
) -> tuple[LockLossEpoch, ...]:
    """Report coincident variability and tracking occupancy, without causality.

    Legacy attribution strings are retained for compatibility. Missing slots
    cannot distinguish scintillation, obstruction, interference or diagnostics
    loss, and C/N0 variability alone does not establish scintillation.
    """
    if not math.isfinite(s4_threshold) or s4_threshold < 0:
        raise ValueError("s4_threshold must be finite and non-negative")
    if minimum_slots < 0:
        raise ValueError("minimum_slots must be non-negative")
    output = []
    for item in epochs:
        if not math.isfinite(item.epoch) or not math.isfinite(item.s4):
            raise ValueError("epoch and S4 must be finite")
        if item.written_slots < 0:
            raise ValueError("written slot count must be non-negative")
        if item.s4 < s4_threshold:
            continue
        attribution = (
            "tracking_under_scintillation"
            if item.written_slots >= minimum_slots
            else "no_tracking_while_scintillating"
        )
        output.append(
            LockLossEpoch(item.epoch, item.s4, item.written_slots, attribution)
        )
    return tuple(sorted(output, key=lambda entry: entry.epoch))


def linear_power(cn0_db_hz: float) -> float:
    """Convert C/N0 to linear Hz, proportional to power at constant noise density."""
    if not math.isfinite(cn0_db_hz):
        raise ValueError("C/N0 must be finite")
    return float(10.0 ** (cn0_db_hz / 10.0))


def s4_index(powers: Sequence[float]) -> float:
    """S4 index sqrt((<P^2> - <P>^2) / <P>^2) of a power window."""
    if len(powers) < 2:
        raise ValueError("at least two powers are required")
    if any(not math.isfinite(power) or power < 0 for power in powers):
        raise ValueError("powers must be finite and non-negative")
    average = mean(powers)
    if average <= 0:
        raise ValueError("powers must be positive")
    variance = mean([(power - average) ** 2 for power in powers])
    return math.sqrt(max(0.0, variance)) / average


def sliding_s4(powers: Sequence[float], window: int) -> list[float]:
    """S4 of every window of consecutive powers, one sample per epoch."""
    if window < 2:
        raise ValueError("window must be at least two")
    return [
        s4_index(powers[start : start + window])
        for start in range(len(powers) - window + 1)
    ]


def roti_proxy(s4_values: Sequence[float], interval_seconds: float = 1.0) -> float:
    """Rate of change proxy: sigma of successive S4 increments per second."""
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("interval must be positive")
    increments = [second - first for first, second in pairwise(s4_values)]
    if len(increments) < 2:
        return math.nan
    return stddev(increments) / interval_seconds


def unambiguous_samples(
    frames: Sequence[Sequence[ScintillationSample]],
) -> list[ScintillationSample]:
    """Keep the signals that no frame reports more than once."""
    repeated = {
        signal
        for frame in frames
        for signal, count in Counter(
            (sample.prn, sample.frequency_channel) for sample in frame
        ).items()
        if count > 1
    }
    return [
        sample
        for frame in frames
        for sample in frame
        if (sample.prn, sample.frequency_channel) not in repeated
    ]


def summarise(
    samples: Sequence[ScintillationSample],
    *,
    window: int = 60,
    interval_seconds: float = 1.0,
) -> tuple[ScintillationSummary, ...]:
    """Per signal S4 index and rate proxy over the last ``window`` epochs."""
    if window < 2:
        raise ValueError("window must be at least two")
    grouped: dict[tuple[str, int], list[float]] = {}
    for sample in samples:
        key = (sample.prn, sample.frequency_channel)
        grouped.setdefault(key, []).append(sample.cn0_db_hz)
    summaries = []
    for (prn, frequency_channel), values in sorted(grouped.items()):
        span = min(window, len(values))
        powers = [linear_power(value) for value in values]
        series = sliding_s4(powers, span) if span >= 2 else []
        summaries.append(
            ScintillationSummary(
                prn=prn,
                frequency_channel=frequency_channel,
                sample_count=len(values),
                mean_cn0_db_hz=mean(values[-window:]),
                s4=series[-1] if series else math.nan,
                roti_proxy=roti_proxy(series, interval_seconds),
            )
        )
    return tuple(summaries)
