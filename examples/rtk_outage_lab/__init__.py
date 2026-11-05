"""Measures RTK degradation and recovery around recorded outages."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from um982py.stats import Vector, finite, norm, percentile, subtract


@dataclass(frozen=True, slots=True)
class Outage:
    """Known correction-link off and on times in absolute GPS seconds."""

    start: float
    end: float


@dataclass(frozen=True, slots=True)
class PositionEpoch:
    """An ECEF solution with an explicit computed, fixed and correction-age state."""

    epoch: float
    position: Vector
    computed: bool
    fixed: bool
    correction_age: float

    @property
    def fresh_fixed(self) -> bool:
        """A computed fixed solution with a finite correction age up to 10 s."""
        return self.computed and self.fixed and 0 <= self.correction_age <= 10


@dataclass(frozen=True, slots=True)
class OutageResult:
    """Observed fix loss and sustained recovery, retaining censored outcomes."""

    start: float
    end: float
    fixed_before: bool | None
    first_nonfixed_after_start_s: float | None
    recovery_after_end_s: float | None
    recovery_censored: bool
    observation_end: float
    maximum_position_step_m: float | None
    maximum_truth_error_m: float | None
    maximum_correction_age_s: float | None
    recovery_status: str
    fresh_fixed_before: bool | None
    first_nonfresh_fixed_after_start_s: float | None


@dataclass(frozen=True, slots=True)
class OutageSummary:
    outages: int
    recovered: int
    recovery_censored: int
    median_observed_recovery_s: float | None
    p90_observed_recovery_s: float | None
    maximum_truth_error_m: float | None


@dataclass(frozen=True, slots=True)
class OutageTimelineEpoch:
    gps_epoch: float
    computed: bool
    fixed: bool
    correction_age_s: float
    truth_error_m: float | None
    fresh_fixed: bool


def epoch_timeline(
    epochs: Sequence[PositionEpoch], truth: Vector | None = None
) -> tuple[OutageTimelineEpoch, ...]:
    return tuple(
        OutageTimelineEpoch(
            item.epoch,
            item.computed,
            item.fixed,
            item.correction_age,
            norm(subtract(item.position, truth))
            if truth is not None and item.computed
            else None,
            item.fresh_fixed,
        )
        for item in epochs
    )


def summarize_outages(results: Sequence[OutageResult]) -> OutageSummary:
    observed = [
        result.recovery_after_end_s
        for result in results
        if result.recovery_after_end_s is not None
    ]
    errors = [
        result.maximum_truth_error_m
        for result in results
        if result.maximum_truth_error_m is not None
    ]
    return OutageSummary(
        outages=len(results),
        recovered=len(observed),
        recovery_censored=sum(result.recovery_censored for result in results),
        median_observed_recovery_s=median(observed) if observed else None,
        p90_observed_recovery_s=percentile(observed, 0.9) if observed else None,
        maximum_truth_error_m=max(errors) if errors else None,
    )


def analyse_outages(
    epochs: Sequence[PositionEpoch],
    outages: Sequence[Outage],
    *,
    truth: Vector | None = None,
    sustained_seconds: float = 3.0,
    max_gap: float = 2.0,
) -> tuple[OutageResult, ...]:
    """Measure receiver recovery from independently recorded link events."""
    finite(sustained_seconds, max_gap)
    if sustained_seconds < 0 or max_gap <= 0 or not epochs:
        raise ValueError(
            "epochs, nonnegative sustained time and positive gap are required"
        )
    if truth is not None:
        finite(*truth)
    for item in epochs:
        finite(item.epoch, *item.position, item.correction_age)
    if any(b.epoch <= a.epoch for a, b in itertools.pairwise(epochs)):
        raise ValueError("position epochs must increase strictly")
    for outage in outages:
        finite(outage.start, outage.end)
        if outage.end <= outage.start:
            raise ValueError("outage end must follow its start")
    if any(b.start <= a.end for a, b in itertools.pairwise(outages)):
        raise ValueError("outages must be ordered and nonoverlapping")
    result = []
    for index, outage in enumerate(outages):
        if outage.start < epochs[0].epoch or outage.end > epochs[-1].epoch:
            raise ValueError("position capture must cover each complete outage")
        limit = min(
            epochs[-1].epoch,
            outages[index + 1].start if index + 1 < len(outages) else epochs[-1].epoch,
        )
        before = [
            item
            for item in epochs
            if item.epoch < outage.start and outage.start - item.epoch <= max_gap
        ]
        window = [item for item in epochs if outage.start <= item.epoch <= limit]
        loss = next(
            (item.epoch - outage.start for item in window if not item.fresh_fixed),
            None,
        )
        raw_loss = next(
            (
                item.epoch - outage.start
                for item in window
                if not (item.computed and item.fixed)
            ),
            None,
        )
        recovery: float | None = None
        run_start: float | None = None
        previous_epoch: float | None = None
        loss_epoch = None if loss is None else outage.start + loss
        for item in window:
            if (
                item.epoch < outage.end
                or loss_epoch is None
                or item.epoch <= loss_epoch
            ):
                continue
            if not item.fresh_fixed:
                run_start = None
            else:
                if (
                    run_start is None
                    or previous_epoch is None
                    or item.epoch - previous_epoch > max_gap
                ):
                    run_start = item.epoch
                if item.epoch - run_start >= sustained_seconds:
                    recovery = run_start - outage.end
                    break
            previous_epoch = item.epoch
        through_end = [item for item in window if item.epoch <= outage.end]
        retained = bool(
            before
            and before[-1].fresh_fixed
            and through_end
            and all(item.fresh_fixed for item in through_end)
            and all(
                b.epoch - a.epoch <= max_gap
                for a, b in itertools.pairwise([before[-1], *through_end])
            )
            and outage.end - through_end[-1].epoch <= max_gap
        )
        if retained:
            recovery = None
            status = "retained"
        elif recovery is not None:
            status = "recovered"
        else:
            status = "censored"
        step_epochs = ([before[-1]] if before else []) + window
        steps = [
            norm(subtract(b.position, a.position))
            for a, b in itertools.pairwise(step_epochs)
            if a.computed and b.computed and b.epoch - a.epoch <= max_gap
        ]
        valid = [item for item in window if item.computed]
        result.append(
            OutageResult(
                outage.start,
                outage.end,
                before[-1].computed and before[-1].fixed if before else None,
                raw_loss,
                recovery,
                status == "censored",
                limit,
                max(steps) if steps else None,
                max(norm(subtract(item.position, truth)) for item in valid)
                if truth is not None and valid
                else None,
                max(item.correction_age for item in valid) if valid else None,
                status,
                before[-1].fresh_fixed if before else None,
                loss,
            )
        )
    return tuple(result)
