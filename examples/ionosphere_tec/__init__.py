"""Computes slant TEC, ROT and ROTI from dual-frequency observations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from examples._observation_arcs import CarrierState
from um982py.geodesy import wavelength
from um982py.stats import mean, stddev

GPS_L1_HZ = 1575.42e6
GPS_L2_HZ = 1227.60e6
IONOSPHERE_COEFFICIENT = 40.3
TECU = 1e16
TECU_PER_METRE = (
    GPS_L1_HZ**2
    * GPS_L2_HZ**2
    / ((GPS_L1_HZ**2 - GPS_L2_HZ**2) * IONOSPHERE_COEFFICIENT * TECU)
)
ROTI_WINDOW_MINUTES = 5.0
SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True, slots=True)
class Observation:
    """Pseudorange in metres and carrier phase in cycles on one frequency."""

    prn: int
    frequency_hz: float
    pseudorange: float
    carrier_phase: float
    carrier_state: CarrierState | None = None


@dataclass(frozen=True, slots=True)
class TecSample:
    """Uncalibrated TEC proxy in TECU of one satellite at one epoch."""

    prn: int
    epoch: float
    tec: float
    arc: int = 0


@dataclass(frozen=True, slots=True)
class TecRate:
    """Rate of TEC in TECU per minute of one satellite at one epoch."""

    prn: int
    epoch: float
    rate: float
    arc: int = 0


@dataclass(frozen=True, slots=True)
class TecIndex:
    """ROTI in TECU per minute of one satellite at one epoch."""

    prn: int
    epoch: float
    index: float
    arc: int = 0


@dataclass(frozen=True, slots=True)
class TecReport:
    """Slant TEC of every paired satellite at one epoch."""

    epoch: float
    prn_count: int
    dual_frequency: bool
    samples: tuple[TecSample, ...]


def tec_scale_per_metre(frequency_a: float, frequency_b: float) -> float:
    """Slant TEC in TECU per metre of differential code delay."""
    high, low = sorted((frequency_a, frequency_b), reverse=True)
    return high**2 * low**2 / ((high**2 - low**2) * IONOSPHERE_COEFFICIENT * TECU)


def _frequency_pair(
    observations: Sequence[Observation],
) -> tuple[Observation, Observation] | None:
    by_frequency: dict[float, Observation] = {}
    for observation in observations:
        by_frequency.setdefault(observation.frequency_hz, observation)
    if len(by_frequency) < 2:
        return None
    if len(by_frequency) > 2:
        raise ValueError("a satellite carries more than two frequencies")
    low_hz, high_hz = sorted(by_frequency)
    return by_frequency[low_hz], by_frequency[high_hz]


def slant_tec(observations: Sequence[Observation]) -> float | None:
    """Return a code TEC proxy including uncalibrated instrumental biases."""
    pair = _frequency_pair(observations)
    if pair is None:
        return None
    low, high = pair
    scale = tec_scale_per_metre(high.frequency_hz, low.frequency_hz)
    return scale * (low.pseudorange - high.pseudorange)


def phase_tec(observations: Sequence[Observation]) -> float | None:
    """Return ambiguity-offset carrier TEC in TECU, or None without a pair."""
    pair = _frequency_pair(observations)
    if pair is None:
        return None
    low, high = pair
    scale = tec_scale_per_metre(high.frequency_hz, low.frequency_hz)
    low_metres = low.carrier_phase * wavelength(low.frequency_hz)
    high_metres = high.carrier_phase * wavelength(high.frequency_hz)
    return scale * (low_metres - high_metres)


def level_tec(code: Sequence[float], phase: Sequence[float]) -> tuple[float, ...]:
    """Level an uninterrupted carrier arc; code biases remain in the result."""
    if len(code) != len(phase):
        raise ValueError("code and phase must have equal length")
    if not code:
        return ()
    offsets = [
        code_value - phase_value
        for code_value, phase_value in zip(code, phase, strict=True)
    ]
    offset = mean(offsets)
    return tuple(phase_value + offset for phase_value in phase)


def tec_report(observations: Sequence[Observation], epoch: float) -> TecReport:
    """Code TEC of every paired satellite of one epoch."""
    by_prn: dict[int, list[Observation]] = {}
    for observation in observations:
        by_prn.setdefault(observation.prn, []).append(observation)
    samples = []
    for prn, group in sorted(by_prn.items()):
        tec = slant_tec(group)
        if tec is not None:
            samples.append(TecSample(prn=prn, epoch=epoch, tec=tec))
    return TecReport(
        epoch=epoch,
        prn_count=len(by_prn),
        dual_frequency=bool(samples),
        samples=tuple(samples),
    )


def rate_of_tec(
    samples: Sequence[TecSample], *, max_gap: float | None = None
) -> tuple[TecRate, ...]:
    """Rate of TEC in TECU per minute from consecutive samples of one satellite."""
    if max_gap is not None and (not math.isfinite(max_gap) or max_gap <= 0):
        raise ValueError("maximum gap must be finite and positive")
    by_prn: dict[tuple[int, int], list[TecSample]] = {}
    for sample in samples:
        by_prn.setdefault((sample.prn, sample.arc), []).append(sample)
    rates = []
    for (prn, arc), group in sorted(by_prn.items()):
        ordered = sorted(group, key=lambda sample: sample.epoch)
        for previous, current in pairwise(ordered):
            minutes = (current.epoch - previous.epoch) / SECONDS_PER_MINUTE
            if minutes > 0 and (max_gap is None or minutes * 60 <= max_gap):
                rate = (current.tec - previous.tec) / minutes
                rates.append(TecRate(prn=prn, epoch=current.epoch, rate=rate, arc=arc))
    return tuple(rates)


def roti(
    rates: Sequence[TecRate], *, window_minutes: float = ROTI_WINDOW_MINUTES
) -> tuple[TecIndex, ...]:
    """ROTI in TECU per minute: the standard deviation of ROT in five minutes."""
    if not math.isfinite(window_minutes) or window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    by_prn: dict[tuple[int, int], list[TecRate]] = {}
    for rate in rates:
        by_prn.setdefault((rate.prn, rate.arc), []).append(rate)
    indexes = []
    window_seconds = window_minutes * SECONDS_PER_MINUTE
    for (prn, arc), group in sorted(by_prn.items()):
        ordered = sorted(group, key=lambda rate: rate.epoch)
        intervals = [b.epoch - a.epoch for a, b in pairwise(ordered)]
        positive = [interval for interval in intervals if interval > 0]
        if not positive:
            continue
        cadence = median(positive)
        cadence_tolerance = max(0.02, cadence * 0.05)
        for current in ordered:
            window = [
                rate
                for rate in ordered
                if current.epoch - window_seconds <= rate.epoch <= current.epoch
            ]
            if (
                len(window) > 1
                and current.epoch - window[0].epoch >= window_seconds - 1e-6
                and all(
                    abs(b.epoch - a.epoch - cadence) <= cadence_tolerance
                    for a, b in pairwise(window)
                )
            ):
                indexes.append(
                    TecIndex(
                        prn=prn,
                        epoch=current.epoch,
                        index=stddev([rate.rate for rate in window]),
                        arc=arc,
                    )
                )
    return tuple(indexes)
