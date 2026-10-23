"""Computes Allan deviation, log-log slope and noise type of a clock."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from um982py.stats import allan_deviation, fractional_frequency

SLOPE_BLOCKS = 64

__all__ = [
    "NOISE_SLOPES",
    "SLOPE_BLOCKS",
    "ClockStability",
    "NoiseType",
    "analyse",
    "classify_noise",
    "frequency_adev",
    "frequency_deviation",
    "log_log_slope",
    "phase_adev",
    "resolved_pairs",
]


class NoiseType(StrEnum):
    """Closed set of power-law noise types keyed by Allan deviation slope."""

    WHITE_PM = "white phase modulation"
    WHITE_FM = "white frequency modulation"
    FLICKER_FM = "flicker frequency modulation"
    RANDOM_WALK_FM = "random walk frequency modulation"
    LINEAR_DRIFT = "linear frequency drift"


NOISE_SLOPES: tuple[tuple[NoiseType, float], ...] = (
    (NoiseType.WHITE_PM, -1.0),
    (NoiseType.WHITE_FM, -0.5),
    (NoiseType.FLICKER_FM, 0.0),
    (NoiseType.RANDOM_WALK_FM, 0.5),
    (NoiseType.LINEAR_DRIFT, 1.0),
)


@dataclass(frozen=True, slots=True)
class ClockStability:
    """Allan deviation report for one clock offset series."""

    sample_count: int
    taus: tuple[float, ...]
    phase_deviation: tuple[float, ...]
    frequency_deviation: tuple[float, ...]
    phase_slope: float | None
    frequency_slope: float | None
    noise: NoiseType | None


def frequency_deviation(
    samples: Sequence[float], tau0: float = 1.0
) -> list[tuple[float, float]]:
    """Allan deviation of the fractional frequency derived from a phase series."""
    return allan_deviation(fractional_frequency(samples, tau0), tau0)


def phase_adev(
    samples: Sequence[float], tau0: float = 1.0
) -> list[tuple[float, float]]:
    """Time error deviation in seconds, the fractional deviation times tau."""
    return [
        (tau, tau * deviation) for tau, deviation in frequency_deviation(samples, tau0)
    ]


def frequency_adev(
    pairs: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Fractional frequency deviation, the time error deviation divided by tau."""
    return [(tau, deviation / tau) for tau, deviation in pairs]


def resolved_pairs(
    samples: Sequence[float], tau0: float = 1.0, *, block_floor: int = SLOPE_BLOCKS
) -> list[tuple[float, float]]:
    """Deviation pairs whose averaging factor keeps at least ``block_floor`` blocks."""
    maximum_factor = len(samples) // block_floor
    if block_floor < 2 or maximum_factor < 2:
        return []
    return [
        (tau, deviation)
        for tau, deviation in phase_adev(samples, tau0)
        if tau <= maximum_factor * tau0
    ]


def log_log_slope(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Least squares slope of log deviation against log tau, or ``None``."""
    if len(pairs) < 2 or any(deviation <= 0 for _, deviation in pairs):
        return None
    abscissae = [math.log(tau) for tau, _ in pairs]
    ordinates = [math.log(deviation) for _, deviation in pairs]
    mean_x = sum(abscissae) / len(abscissae)
    mean_y = sum(ordinates) / len(ordinates)
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(abscissae, ordinates, strict=True)
    )
    variance = sum((x - mean_x) ** 2 for x in abscissae)
    if variance == 0:
        return None
    return covariance / variance


def classify_noise(slope: float) -> NoiseType:
    """Nearest tabulated noise type for a fractional frequency slope."""
    return min(NOISE_SLOPES, key=lambda entry: abs(entry[1] - slope))[0]


def analyse(samples: Sequence[float], *, tau0: float = 1.0) -> ClockStability:
    """Build the Allan deviation report for a clock offset series."""
    pairs = resolved_pairs(samples, tau0)
    frequency = frequency_adev(pairs)
    phase_slope = log_log_slope(pairs)
    frequency_slope = log_log_slope(frequency)
    return ClockStability(
        sample_count=len(samples),
        taus=tuple(tau for tau, _ in pairs),
        phase_deviation=tuple(deviation for _, deviation in pairs),
        frequency_deviation=tuple(deviation for _, deviation in frequency),
        phase_slope=phase_slope,
        frequency_slope=frequency_slope,
        noise=None if frequency_slope is None else classify_noise(frequency_slope),
    )
