"""Computes Allan deviation, log-log slope and noise type of a clock."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from um982py.stats import allan_deviation, fractional_frequency

SLOPE_BLOCKS = 64
MINIMUM_CLASSIFICATION_TAUS = 3

__all__ = [
    "NOISE_SLOPES",
    "SLOPE_BLOCKS",
    "ClockStability",
    "NoiseType",
    "OverlappingPoint",
    "analyse",
    "classify_noise",
    "frequency_adev",
    "frequency_deviation",
    "log_log_slope",
    "overlapping_adev",
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
    overlapping: tuple[OverlappingPoint, ...] = ()
    overlapping_slope: float | None = None


@dataclass(frozen=True, slots=True)
class OverlappingPoint:
    """Overlapping Allan deviation at one averaging time (NIST SP 1065)."""

    tau: float
    deviation: float
    terms: int
    """Overlapping second differences in the estimate."""
    independent: int
    """Non-overlapping second differences, used for the simple interval."""

    @property
    def interval(self) -> tuple[float, float]:
        """Simple one-sigma interval deviation * (1 -/+ 1/sqrt(independent))."""
        half = self.deviation / math.sqrt(self.independent)
        return max(0.0, self.deviation - half), self.deviation + half


def overlapping_adev(
    phase: Sequence[float], tau0: float = 1.0
) -> tuple[OverlappingPoint, ...]:
    """Overlapping ADEV from a phase series at octave averaging factors.

    sigma^2(m tau0) = sum (x[i+2m] - 2 x[i+m] + x[i])^2 / (2 (m tau0)^2 (N - 2m)),
    for factors up to (N - 1) // 4 so each tau keeps at least three
    non-overlapping second differences.
    """
    if not math.isfinite(tau0) or tau0 <= 0:
        raise ValueError("tau0 must be finite and positive")
    count = len(phase)
    points = []
    factor = 1
    while factor <= (count - 1) // 4:
        terms = count - 2 * factor
        total = math.fsum(
            (phase[i + 2 * factor] - 2 * phase[i + factor] + phase[i]) ** 2
            for i in range(terms)
        )
        tau = factor * tau0
        points.append(
            OverlappingPoint(
                tau=tau,
                deviation=math.sqrt(total / (2 * tau * tau * terms)),
                terms=terms,
                independent=(count - 1) // factor - 1,
            )
        )
        factor *= 2
    return tuple(points)


def frequency_deviation(
    samples: Sequence[float], tau0: float = 1.0
) -> list[tuple[float, float]]:
    """Allan deviation of the fractional frequency derived from a phase series."""
    return allan_deviation(fractional_frequency(samples, tau0), tau0)


def phase_adev(
    samples: Sequence[float], tau0: float = 1.0
) -> list[tuple[float, float]]:
    """Return tau times frequency ADEV in seconds. This is not TDEV."""
    return [
        (tau, tau * deviation) for tau, deviation in frequency_deviation(samples, tau0)
    ]


def frequency_adev(
    pairs: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Recover frequency ADEV by dividing tau-scaled ADEV by tau."""
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
    overlapping = overlapping_adev(samples, tau0)
    overlapping_slope = (
        log_log_slope([(point.tau, point.deviation) for point in overlapping])
        if len(overlapping) >= MINIMUM_CLASSIFICATION_TAUS
        else None
    )
    # A noise type needs a slope over at least three averaging times; the
    # overlapping estimator reaches longer taus than the 64-block series.
    return ClockStability(
        sample_count=len(samples),
        taus=tuple(tau for tau, _ in pairs),
        phase_deviation=tuple(deviation for _, deviation in pairs),
        frequency_deviation=tuple(deviation for _, deviation in frequency),
        phase_slope=phase_slope,
        frequency_slope=frequency_slope,
        noise=None if overlapping_slope is None else classify_noise(overlapping_slope),
        overlapping=overlapping,
        overlapping_slope=overlapping_slope,
    )
