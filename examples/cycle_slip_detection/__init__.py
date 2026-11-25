"""Detects cycle slips from Doppler-predicted phase increments."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from um982py.geodesy import wavelength

SLIP_THRESHOLD_CYCLES = 0.5
GEOMETRY_FREE_THRESHOLD_METRES = 0.05
DEFAULT_MAX_GAP_SECONDS = 2.0
LOCK_CONTINUITY_TOLERANCE_SECONDS = 0.5
MINIMUM_COMMON_MODE_SATELLITES = 4


@dataclass(frozen=True, slots=True)
class Observation:
    """Carrier phase in cycles and Doppler in Hz of one satellite at one epoch."""

    prn: int
    epoch: float
    carrier_phase: float
    doppler: float
    lock_time: float | None = None
    """Receiver lock duration in seconds, when available."""


@dataclass(frozen=True, slots=True)
class DualFrequencyPhase:
    """Carrier phase in cycles on two frequencies of one satellite at one epoch."""

    prn: int
    epoch: float
    high_hz: float
    high_cycles: float
    low_hz: float
    low_cycles: float


@dataclass(frozen=True, slots=True)
class Slip:
    """A carrier-phase discontinuity that the Doppler does not predict."""

    prn: int
    epoch: float
    cycles: float


@dataclass(frozen=True, slots=True)
class GeometryFreeSlip:
    """A discontinuity of the geometry-free combination in metres."""

    prn: int
    epoch: float
    metres: float


@dataclass(frozen=True, slots=True)
class SlipReport:
    """Detected slip epochs of one satellite."""

    prn: int
    epochs: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CommonModeEvent:
    """Slip flags shared by several satellites at one epoch."""

    epoch: float
    prns: tuple[int, ...]
    median_cycles: float


def predicted_increment(doppler_a: float, doppler_b: float, interval: float) -> float:
    """Carrier phase change in cycles predicted from the mean Doppler in Hz."""
    return 0.5 * (doppler_a + doppler_b) * interval


def doppler_residuals(
    observations: Sequence[Observation],
    *,
    max_gap: float = DEFAULT_MAX_GAP_SECONDS,
) -> tuple[tuple[float, float], ...]:
    """Phase residuals of one ordered satellite, within continuous tracking.

    Gaps and reported lock resets start new arcs. They are unobservable
    intervals, not evidence that no slip occurred. Lock time must grow by
    the epoch interval: a reacquisition between two kept epochs, which
    leaves the lock time no larger than before, also starts a new arc. Do
    not prefilter large residuals: those are exactly the discontinuities
    being tested.
    """
    if not math.isfinite(max_gap) or max_gap <= 0:
        raise ValueError("max_gap must be finite and positive")
    if len({item.prn for item in observations}) > 1:
        raise ValueError("residuals require one satellite")
    for item in observations:
        if not all(
            math.isfinite(value)
            for value in (item.epoch, item.carrier_phase, item.doppler)
        ):
            raise ValueError("observation values must be finite")
        if item.lock_time is not None and (
            not math.isfinite(item.lock_time) or item.lock_time < 0
        ):
            raise ValueError("lock time must be finite and nonnegative")
    residuals = []
    for previous, current in pairwise(observations):
        interval = current.epoch - previous.epoch
        if interval <= 0:
            raise ValueError("satellite epochs must increase strictly")
        if interval > max_gap or not _lock_continues(previous, current, interval):
            continue
        measured = current.carrier_phase - previous.carrier_phase
        predicted = predicted_increment(previous.doppler, current.doppler, interval)
        residuals.append((current.epoch, measured - predicted))
    return tuple(residuals)


def _lock_continues(
    previous: Observation, current: Observation, interval: float
) -> bool:
    if previous.lock_time is None or current.lock_time is None:
        return True
    return (
        current.lock_time
        >= previous.lock_time + interval - LOCK_CONTINUITY_TOLERANCE_SECONDS
    )


def epoch_common_mode(
    residuals: dict[int, tuple[tuple[float, float], ...]],
) -> dict[float, float]:
    """Median residual of each epoch shared by enough satellites, in cycles.

    Receiver clock frequency changes inside an interval are not described by
    the two Doppler samples at its ends and shift every satellite's residual
    of one frequency by the same number of cycles.
    """
    by_epoch: dict[float, list[float]] = {}
    for series in residuals.values():
        for epoch, residual in series:
            by_epoch.setdefault(epoch, []).append(residual)
    common = {}
    for epoch, values in by_epoch.items():
        if len(values) >= MINIMUM_COMMON_MODE_SATELLITES:
            ordered = sorted(values)
            middle = len(ordered) // 2
            common[epoch] = (
                ordered[middle]
                if len(ordered) % 2
                else 0.5 * (ordered[middle - 1] + ordered[middle])
            )
    return common


def detect_slips(
    observations: Sequence[Observation],
    *,
    threshold_cycles: float = SLIP_THRESHOLD_CYCLES,
    max_gap: float = DEFAULT_MAX_GAP_SECONDS,
    remove_common_mode: bool = True,
) -> tuple[Slip, ...]:
    """Slips whose phase increment disagrees with the Doppler prediction.

    With ``remove_common_mode`` the per-epoch median residual of at least
    ``MINIMUM_COMMON_MODE_SATELLITES`` satellites is subtracted first, so a
    receiver clock effect shared by all satellites is not counted as a slip.
    """
    if not math.isfinite(threshold_cycles) or threshold_cycles <= 0:
        raise ValueError("threshold_cycles must be finite and positive")
    if not math.isfinite(max_gap) or max_gap <= 0:
        raise ValueError("max_gap must be finite and positive")
    by_prn: dict[int, list[Observation]] = {}
    for observation in observations:
        by_prn.setdefault(observation.prn, []).append(observation)
    residuals = {
        prn: doppler_residuals(group, max_gap=max_gap)
        for prn, group in sorted(by_prn.items())
    }
    common = epoch_common_mode(residuals) if remove_common_mode else {}
    slips = []
    for prn, series in residuals.items():
        for epoch, residual in series:
            corrected = residual - common.get(epoch, 0.0)
            if abs(corrected) >= threshold_cycles:
                slips.append(Slip(prn=prn, epoch=epoch, cycles=corrected))
    return tuple(slips)


def geometry_free(phase: DualFrequencyPhase) -> float:
    """Geometry-free carrier combination in metres."""
    # Geometric range cancels after converting both phases to metres, but
    # atmospheric and phase ambiguity effects can still produce a jump.
    low = wavelength(phase.low_hz) * phase.low_cycles
    high = wavelength(phase.high_hz) * phase.high_cycles
    return low - high


def geometry_free_slips(
    phases: Sequence[DualFrequencyPhase],
    *,
    threshold_metres: float = GEOMETRY_FREE_THRESHOLD_METRES,
    max_gap: float = DEFAULT_MAX_GAP_SECONDS,
) -> tuple[GeometryFreeSlip, ...]:
    """Slips that jump the geometry-free combination by more than a metre bound."""
    if not math.isfinite(threshold_metres) or threshold_metres <= 0:
        raise ValueError("threshold_metres must be finite and positive")
    if not math.isfinite(max_gap) or max_gap <= 0:
        raise ValueError("max_gap must be finite and positive")
    by_prn: dict[int, list[DualFrequencyPhase]] = {}
    for phase in phases:
        if (
            not all(
                math.isfinite(value)
                for value in (
                    phase.epoch,
                    phase.high_hz,
                    phase.high_cycles,
                    phase.low_hz,
                    phase.low_cycles,
                )
            )
            or not 0 < phase.low_hz < phase.high_hz
        ):
            raise ValueError("finite phases and high_hz > low_hz > 0 are required")
        by_prn.setdefault(phase.prn, []).append(phase)
    slips = []
    for prn, group in sorted(by_prn.items()):
        for previous, current in pairwise(group):
            interval = current.epoch - previous.epoch
            if interval <= 0:
                raise ValueError("satellite epochs must increase strictly")
            if interval > max_gap or (previous.high_hz, previous.low_hz) != (
                current.high_hz,
                current.low_hz,
            ):
                continue
            jump = geometry_free(current) - geometry_free(previous)
            if abs(jump) >= threshold_metres:
                slips.append(
                    GeometryFreeSlip(prn=prn, epoch=current.epoch, metres=jump)
                )
    return tuple(slips)


def common_mode_events(
    slips: Sequence[Slip], *, minimum_prns: int = 3
) -> tuple[CommonModeEvent, ...]:
    """Epochs where many satellites flag together, pointing at the clock."""
    if minimum_prns < 2:
        raise ValueError("minimum_prns must be at least 2")
    by_epoch: dict[float, list[Slip]] = {}
    for slip in slips:
        by_epoch.setdefault(slip.epoch, []).append(slip)
    events = []
    for epoch in sorted(by_epoch):
        group = by_epoch[epoch]
        prns = sorted({slip.prn for slip in group})
        if len(prns) < minimum_prns:
            continue
        magnitudes = sorted(abs(slip.cycles) for slip in group)
        middle = len(magnitudes) // 2
        median = (
            magnitudes[middle]
            if len(magnitudes) % 2
            else 0.5 * (magnitudes[middle - 1] + magnitudes[middle])
        )
        events.append(
            CommonModeEvent(epoch=epoch, prns=tuple(prns), median_cycles=median)
        )
    return tuple(events)


def report(slips: Sequence[Slip | GeometryFreeSlip]) -> tuple[SlipReport, ...]:
    """Group detected slips into the epochs of each satellite."""
    by_prn: dict[int, list[float]] = {}
    for slip in slips:
        by_prn.setdefault(slip.prn, []).append(slip.epoch)
    return tuple(
        SlipReport(prn=prn, epochs=tuple(sorted(epochs)))
        for prn, epochs in sorted(by_prn.items())
    )
