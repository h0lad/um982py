"""Measures double-difference noise from synchronized shared-antenna captures."""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, stdev

from um982py.measurement import RangeSample, SignalKey
from um982py.stats import correlation, finite, is_continuous


@dataclass(frozen=True, slots=True)
class DoubleDifference:
    """An ambiguity-bearing double difference with its propagated sigma."""

    epoch: float
    key: SignalKey
    reference: SignalKey
    code_m: float
    phase_m: float
    code_sigma_m: float
    phase_sigma_m: float
    arc: int


@dataclass(frozen=True, slots=True)
class NoiseEstimate:
    """Centered double-difference statistics for one uninterrupted arc."""

    key: SignalKey
    arc: int
    samples: int
    code_dd_std_m: float
    phase_dd_std_m: float
    equal_receiver_code_std_m: float
    equal_receiver_phase_std_m: float
    code_sigma_ratio: float
    phase_sigma_ratio: float
    phase_lag1_correlation: float | None


def double_differences(
    first: Sequence[RangeSample],
    second: Sequence[RangeSample],
    *,
    reference_prn: int,
    tolerance: float = 0.0,
    max_gap: float = 2.0,
    phase_tolerance: float = 0.5,
) -> tuple[DoubleDifference, ...]:
    """Join epochs once and form intra-signal, intra-system double differences."""
    finite(tolerance, max_gap, phase_tolerance)
    if not 0 <= tolerance < max_gap or phase_tolerance <= 0:
        raise ValueError(
            "join tolerance must be nonnegative and smaller than a positive gap"
        )
    if tolerance != 0:
        raise ValueError(
            "noise estimation requires exactly synchronized receiver epochs"
        )
    by_epoch: list[dict[float, dict[SignalKey, RangeSample]]] = []
    for source in (first, second):
        epochs: dict[float, dict[SignalKey, RangeSample]] = defaultdict(dict)
        for sample in source:
            if sample.key in epochs[sample.epoch]:
                raise ValueError("duplicate signal epoch in receiver capture")
            epochs[sample.epoch][sample.key] = sample
        by_epoch.append(epochs)
    first_epochs, second_epochs = by_epoch
    second_times = sorted(second_epochs)
    cursor = 0
    output = []
    previous: dict[
        SignalKey, tuple[RangeSample, RangeSample, RangeSample, RangeSample]
    ] = {}
    arcs: dict[SignalKey, int] = defaultdict(int)
    for epoch in sorted(first_epochs):
        while cursor < len(second_times) and second_times[cursor] < epoch - tolerance:
            cursor += 1
        if cursor >= len(second_times) or abs(second_times[cursor] - epoch) > tolerance:
            continue
        first_signals = first_epochs[epoch]
        second_signals = second_epochs[second_times[cursor]]
        cursor += 1
        for key in sorted(first_signals.keys() & second_signals.keys()):
            if key.prn == reference_prn:
                continue
            reference = SignalKey(key.system, reference_prn, key.signal)
            if reference not in first_signals or reference not in second_signals:
                continue
            samples = (
                first_signals[key],
                second_signals[key],
                first_signals[reference],
                second_signals[reference],
            )
            previous_samples = previous.get(key)
            if previous_samples is None or any(
                not is_continuous(
                    before, after, max_gap=max_gap, phase_tolerance=phase_tolerance
                )
                for before, after in zip(previous_samples, samples, strict=True)
            ):
                arcs[key] += 1
            first_signal, second_signal, first_reference, second_reference = samples
            output.append(
                DoubleDifference(
                    epoch,
                    key,
                    reference,
                    (first_signal.code_m - second_signal.code_m)
                    - (first_reference.code_m - second_reference.code_m),
                    (first_signal.phase_m - second_signal.phase_m)
                    - (first_reference.phase_m - second_reference.phase_m),
                    math.sqrt(sum(item.code_std_m**2 for item in samples)),
                    math.sqrt(sum(item.phase_std_m**2 for item in samples)),
                    arcs[key],
                )
            )
            previous[key] = samples
    return tuple(output)


def estimate_noise(
    differences: Sequence[DoubleDifference],
) -> tuple[NoiseEstimate, ...]:
    """Estimate double-difference noise and per-receiver noise.

    The per-receiver estimate assumes four equal, independent observation noises.
    """
    groups: dict[tuple[SignalKey, int], list[DoubleDifference]] = defaultdict(list)
    for sample in differences:
        groups[sample.key, sample.arc].append(sample)
    estimates = []
    for (key, arc), samples in sorted(groups.items()):
        if len(samples) < 3:
            continue
        code = [sample.code_m for sample in samples]
        phase = [sample.phase_m for sample in samples]
        code_std, phase_std = stdev(code), stdev(phase)
        code_sigma = math.sqrt(fmean(sample.code_sigma_m**2 for sample in samples))
        phase_sigma = math.sqrt(fmean(sample.phase_sigma_m**2 for sample in samples))
        estimates.append(
            NoiseEstimate(
                key,
                arc,
                len(samples),
                code_std,
                phase_std,
                code_std / 2,
                phase_std / 2,
                code_std / code_sigma,
                phase_std / phase_sigma,
                correlation(phase[:-1], phase[1:]),
            )
        )
    return tuple(estimates)
