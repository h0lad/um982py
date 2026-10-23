"""Separates common-mode code and carrier jumps from isolated slips."""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from um982py.measurement import RangeSample
from um982py.stats import finite


@dataclass(frozen=True, slots=True)
class ClockJump:
    """A common-mode discontinuity candidate in code or carrier range."""

    epoch: float
    code_jump_m: float | None
    phase_jump_m: float | None
    agreeing_code: int
    agreeing_phase: int
    common_satellites: int
    classification: str


def clock_residuals(
    before: Sequence[RangeSample],
    after: Sequence[RangeSample],
    *,
    max_gap: float = 2.0,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Code and phase changes minus integrated Doppler on common locked satellites."""
    finite(max_gap)
    if max_gap <= 0:
        raise ValueError("maximum gap must be positive")
    if not before or not after:
        return (), ()
    if (
        len({sample.epoch for sample in before}) != 1
        or len({sample.epoch for sample in after}) != 1
    ):
        raise ValueError("each input must contain one receiver epoch")
    if any(
        sample.key.system != 0 or sample.key.signal != 0 for sample in (*before, *after)
    ):
        raise ValueError("clock consensus uses one GPS L1 observation per satellite")
    first = {sample.key: sample for sample in before}
    last = {sample.key: sample for sample in after}
    if len(first) != len(before) or len(last) != len(after):
        raise ValueError("duplicate satellite in clock consensus")
    dt = after[0].epoch - before[0].epoch
    if not 0 < dt <= max_gap:
        return (), ()
    code, phase = [], []
    for key in sorted(first.keys() & last.keys()):
        a, b = first[key], last[key]
        if b.lock_seconds < a.lock_seconds + dt - 0.02:
            continue
        predicted = (a.rate_mps + b.rate_mps) * dt / 2
        code.append(b.code_m - a.code_m - predicted)
        phase.append(b.phase_m - a.phase_m - predicted)
    return tuple(code), tuple(phase)


def detect_clock_jumps(
    before: Sequence[RangeSample],
    after: Sequence[RangeSample],
    *,
    threshold_m: float = 1000.0,
    agreement_m: float = 10.0,
    minimum_satellites: int = 4,
    fraction: float = 0.75,
    max_gap: float = 2.0,
) -> ClockJump | None:
    """Compare range changes with integrated Doppler across one receiver epoch."""
    finite(threshold_m, agreement_m, fraction)
    if threshold_m <= agreement_m or agreement_m <= 0:
        raise ValueError("threshold must exceed a positive agreement tolerance")
    if minimum_satellites < 4 or not 0.5 < fraction <= 1:
        raise ValueError(
            "use at least four satellites and a majority agreement fraction"
        )
    code, phase = clock_residuals(before, after, max_gap=max_gap)
    if len(code) < minimum_satellites:
        return None

    def consensus(values: Sequence[float]) -> tuple[float | None, int]:
        center = median(values)
        count = sum(abs(value - center) <= agreement_m for value in values)
        valid = (
            abs(center) >= threshold_m
            and count >= minimum_satellites
            and count / len(values) >= fraction
        )
        return (center if valid else None), count

    code_jump, code_count = consensus(code)
    phase_jump, phase_count = consensus(phase)
    if code_jump is None and phase_jump is None:
        return None
    return ClockJump(
        after[0].epoch,
        code_jump,
        phase_jump,
        code_count,
        phase_count,
        len(code),
        "code_and_phase"
        if code_jump is not None and phase_jump is not None
        else "code_only"
        if code_jump is not None
        else "phase_only",
    )
