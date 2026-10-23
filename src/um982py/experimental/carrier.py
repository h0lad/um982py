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
    count = 0
    for sample in samples:
        if previous is not None and sample.epoch <= previous.epoch:
            raise ValueError("sample epochs must increase strictly")
        reset = previous is None or not is_continuous(
            previous, sample, max_gap=max_gap, phase_tolerance=phase_tolerance
        )
        if reset:
            smoothed, count = sample.code_m, 1
        else:
            if previous is None:
                raise RuntimeError("missing previous sample in continuous arc")
            count = min(window, count + 1)
            # Advance the previous smoothed range by the carrier-phase change,
            # then blend it with the new code range. The capped count limits
            # how slowly the filter responds, while a broken arc restarts above.
            smoothed = sample.code_m / count + (1 - 1 / count) * (
                smoothed + sample.phase_m - previous.phase_m
            )
        output.append(SmoothedCode(sample.epoch, sample.code_m, smoothed, count, reset))
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
    for sample in samples:
        if previous is not None and sample.epoch <= previous.epoch:
            raise ValueError("sample epochs must increase strictly")
        reset = previous is None or not is_continuous(
            previous, sample, max_gap=max_gap, phase_tolerance=phase_tolerance
        )
        cmc = sample.code_m - sample.phase_m
        if reset:
            origin, filtered = cmc, 0.0
            output.append(Divergence(sample.epoch, 0.0, None, None, False, True))
        else:
            if previous is None:
                raise RuntimeError("missing previous sample in continuous arc")
            dt = sample.epoch - previous.epoch
            rate = (cmc - (previous.code_m - previous.phase_m)) / dt
            alpha = -math.expm1(-dt / tau)
            filtered += alpha * (rate - filtered)
            output.append(
                Divergence(
                    sample.epoch,
                    cmc - origin,
                    rate,
                    filtered,
                    abs(filtered) > threshold,
                    False,
                )
            )
        previous = sample
    return tuple(output)
