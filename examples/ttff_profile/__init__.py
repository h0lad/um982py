"""Measures time to first fix after a documented reset."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from examples.rtk_quality import FixClass, classify
from um982py.commands.core import Command
from um982py.commands.system import reset
from um982py.commands.types import ResetTarget
from um982py.messages import CommandResponse
from um982py.messages.enums import SolutionStatus
from um982py.stats import mean, stddev

FIX_ORDER: Mapping[FixClass, int] = MappingProxyType(
    {
        FixClass.NONE: 0,
        FixClass.SINGLE: 1,
        FixClass.FLOAT: 2,
        FixClass.FIXED: 3,
        FixClass.PPP: 1,
        FixClass.PPP_CONVERGING: 1,
    }
)


class StartKind(StrEnum):
    """Documented receiver start selected by the reset command."""

    COLD = "cold"
    WARM = "warm"

    @property
    def reset_targets(self) -> tuple[ResetTarget, ...]:
        """Reset targets that produce this documented start."""
        return (ResetTarget.ALL,) if self is StartKind.COLD else ()

    def reset_command(self) -> Command[CommandResponse]:
        """RESET command that produces this documented start."""
        return reset(*self.reset_targets)


@dataclass(frozen=True, slots=True)
class FixEpoch:
    """Solution status, position type and satellite count of one epoch."""

    seconds: float
    solution_status: int
    position_type: int
    satellites: int

    @property
    def is_computed(self) -> bool:
        """True when the receiver reports a computed solution."""
        return self.solution_status == SolutionStatus.SOL_COMPUTED

    @property
    def fix_class(self) -> FixClass:
        """Return the category of the reported position type."""
        return classify(self.position_type)


@dataclass(frozen=True, slots=True)
class TtffMeasurement:
    """First epoch at the target class after one documented reset."""

    start: StartKind
    reset_seconds: float
    target: FixClass
    fix_seconds: float | None

    @property
    def ttff(self) -> float | None:
        """Seconds from the reset to the first epoch at the target class."""
        if self.fix_seconds is None:
            return None
        return self.fix_seconds - self.reset_seconds


@dataclass(frozen=True, slots=True)
class TtffStatistics:
    """Repeatability of the time to first fix over runs of one start kind."""

    start: StartKind
    runs: int
    mean_seconds: float
    stddev_seconds: float
    minimum_seconds: float
    maximum_seconds: float

    @property
    def spread_seconds(self) -> float:
        """Largest minus smallest measured time to first fix."""
        return self.maximum_seconds - self.minimum_seconds


@dataclass(frozen=True, slots=True)
class StartComparison:
    """Mean time to first fix of a cold start against a warm start."""

    cold_seconds: float
    warm_seconds: float
    difference_seconds: float
    documented_order: bool


def first_fix(
    epochs: Sequence[FixEpoch],
    *,
    after: float,
    target: FixClass = FixClass.SINGLE,
) -> FixEpoch | None:
    """First computed epoch at or after ``after`` reaching the target class."""

    def matches(actual: FixClass) -> bool:
        if target is FixClass.PPP:
            return actual is FixClass.PPP
        if target is FixClass.PPP_CONVERGING:
            return actual in (FixClass.PPP_CONVERGING, FixClass.PPP)
        return FIX_ORDER[actual] >= FIX_ORDER[target]

    return next(
        (
            epoch
            for epoch in epochs
            if epoch.seconds >= after and epoch.is_computed and matches(epoch.fix_class)
        ),
        None,
    )


def fix_transitions(epochs: Sequence[FixEpoch]) -> tuple[tuple[FixClass, float], ...]:
    """First epoch at each fix class the timeline newly reaches, in order."""
    transitions: list[tuple[FixClass, float]] = []
    highest = 0
    seen_ppp: set[FixClass] = set()
    for epoch in epochs:
        if not epoch.is_computed:
            continue
        level = FIX_ORDER[epoch.fix_class]
        if epoch.fix_class in (FixClass.PPP_CONVERGING, FixClass.PPP):
            if epoch.fix_class not in seen_ppp:
                seen_ppp.add(epoch.fix_class)
                transitions.append((epoch.fix_class, epoch.seconds))
            highest = max(highest, level)
        elif level > highest:
            highest = level
            transitions.append((epoch.fix_class, epoch.seconds))
    return tuple(transitions)


def measure(
    epochs: Sequence[FixEpoch],
    *,
    start: StartKind,
    reset_seconds: float,
    target: FixClass = FixClass.SINGLE,
) -> TtffMeasurement:
    """Measure the time to first fix of one run from its reset onward."""
    if not math.isfinite(reset_seconds):
        raise ValueError("reset_seconds must be finite")
    found = first_fix(epochs, after=reset_seconds, target=target)
    return TtffMeasurement(
        start=start,
        reset_seconds=reset_seconds,
        target=target,
        fix_seconds=None if found is None else found.seconds,
    )


def repeatability(runs: Sequence[TtffMeasurement]) -> TtffStatistics:
    """Mean, standard deviation, extremes and spread of repeated runs."""
    if not runs:
        raise ValueError("at least one run is required")
    if len({run.start for run in runs}) != 1:
        raise ValueError("a repeatability set mixes start kinds")
    values = []
    for run in runs:
        ttff = run.ttff
        if ttff is None:
            raise ValueError("a run reached no fix and has no time to first fix")
        values.append(ttff)
    return TtffStatistics(
        start=runs[0].start,
        runs=len(values),
        mean_seconds=mean(values),
        stddev_seconds=stddev(values),
        minimum_seconds=min(values),
        maximum_seconds=max(values),
    )


def compare_starts(
    cold: TtffStatistics,
    warm: TtffStatistics,
    *,
    tolerance_seconds: float = 0.0,
) -> StartComparison:
    """Check that a warm start fixes sooner than a cold start, as documented."""
    if cold.start is not StartKind.COLD or warm.start is not StartKind.WARM:
        raise ValueError("compare a cold statistic with a warm statistic")
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must not be negative")
    return StartComparison(
        cold_seconds=cold.mean_seconds,
        warm_seconds=warm.mean_seconds,
        difference_seconds=cold.mean_seconds - warm.mean_seconds,
        documented_order=warm.mean_seconds + tolerance_seconds < cold.mean_seconds,
    )
