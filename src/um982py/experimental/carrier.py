"""Experimental carrier smoothing and code-carrier divergence models."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.measurement import RangeSample
from um982py.stats import finite, is_continuous


@dataclass(frozen=True, slots=True)
class SmoothedCode:
    """A smoothed pseudorange and its arc population."""

    epoch: float
    raw_m: float
    smoothed_m: float
    count: int
    reset: bool


def smooth_code(
    samples: Sequence[RangeSample],
    *,
    window: int = 100,
    max_gap: float = 2.0,
    phase_tolerance: float = 0.5,
) -> tuple[SmoothedCode, ...]:
    """Run the capped Hatch recursion independently on each continuous arc."""
    if type(window) is not int or window < 1:
        raise ValueError("window must be a positive integer")
    output = []
    previous: RangeSample | None = None
    smoothed = 0.0
    window_samples = 0
    for sample in samples:
        if previous is not None and sample.epoch <= previous.epoch:
            raise ValueError("sample epochs must increase strictly")
        reset = previous is None or not is_continuous(
            previous, sample, max_gap=max_gap, phase_tolerance=phase_tolerance
        )
        if reset:
            smoothed, window_samples = sample.code_m, 1
        else:
            if previous is None:
                raise RuntimeError("missing previous sample in continuous arc")
            window_samples = min(window, window_samples + 1)
            smoothed = sample.code_m / window_samples + (1 - 1 / window_samples) * (
                smoothed + sample.phase_m - previous.phase_m
            )
        output.append(
            SmoothedCode(sample.epoch, sample.code_m, smoothed, window_samples, reset)
        )
        previous = sample
    return tuple(output)


@dataclass(frozen=True, slots=True)
class Divergence:
    """Code-minus-carrier rate and its exponential low-pass in metres per second."""

    epoch: float
    change_m: float
    rate_mps: float | None
    filtered_mps: float | None
    exceeds_threshold: bool
    reset: bool
    noise_mps: float | None = None
    """Expected filtered-rate noise sigma_r * alpha / sqrt(2 - alpha), where
    sigma_r is the robust scatter of this arc's earlier rates. It is ``None`` until
    the arc has ``NOISE_MINIMUM_RATES`` rates."""
    significant: bool = False
    """The filtered rate exceeds both the threshold and three noise sigmas."""


NOISE_MINIMUM_RATES = 10


def _robust_sigma(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = ordered[len(ordered) // 2]
    deviations = sorted(abs(value - middle) for value in values)
    return 1.4826 * deviations[len(deviations) // 2]


def monitor_divergence(
    samples: Sequence[RangeSample],
    *,
    tau: float = 100.0,
    threshold: float = 0.05,
    max_gap: float = 2.0,
    phase_tolerance: float = 0.5,
) -> tuple[Divergence, ...]:
    """Filter code-minus-carrier differences using the actual receiver cadence."""
    finite(tau, threshold)
    if tau <= 0 or threshold <= 0:
        raise ValueError("tau and threshold must be positive")
    previous: RangeSample | None = None
    output = []
    origin = filtered = 0.0
    rates: list[float] = []
    for sample in samples:
        if previous is not None and sample.epoch <= previous.epoch:
            raise ValueError("sample epochs must increase strictly")
        reset = previous is None or not is_continuous(
            previous, sample, max_gap=max_gap, phase_tolerance=phase_tolerance
        )
        cmc = sample.code_m - sample.phase_m
        if reset:
            origin, filtered = cmc, 0.0
            rates = []
            output.append(Divergence(sample.epoch, 0.0, None, None, False, True))
        else:
            if previous is None:
                raise RuntimeError("missing previous sample in continuous arc")
            dt = sample.epoch - previous.epoch
            rate = (cmc - (previous.code_m - previous.phase_m)) / dt
            alpha = -math.expm1(-dt / tau)
            filtered += alpha * (rate - filtered)
            noise = (
                _robust_sigma(rates) * alpha / math.sqrt(2.0 - alpha)
                if len(rates) >= NOISE_MINIMUM_RATES
                else None
            )
            rates.append(rate)
            exceeds = abs(filtered) > threshold
            output.append(
                Divergence(
                    sample.epoch,
                    cmc - origin,
                    rate,
                    filtered,
                    exceeds,
                    False,
                    noise,
                    exceeds and noise is not None and abs(filtered) > 3.0 * noise,
                )
            )
        previous = sample
    return tuple(output)
