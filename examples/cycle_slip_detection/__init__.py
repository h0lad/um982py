"""Detects cycle slips from Doppler-predicted phase increments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from um982py.geodesy import wavelength

GPS_L1_HZ = 1575.42e6
GPS_L2_HZ = 1227.60e6
SLIP_THRESHOLD_CYCLES = 0.5
GEOMETRY_FREE_THRESHOLD_METRES = 0.05


@dataclass(frozen=True, slots=True)
class Observation:
    """Carrier phase in cycles and Doppler in Hz of one satellite at one epoch."""

    prn: int
    epoch: float
    carrier_phase: float
    doppler: float


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
) -> tuple[tuple[float, float], ...]:
    """Epoch and measured minus predicted phase increment of one satellite."""
    ordered = sorted(observations, key=lambda observation: observation.epoch)
    residuals = []
    for previous, current in pairwise(ordered):
        interval = current.epoch - previous.epoch
        if interval <= 0:
            continue
        measured = current.carrier_phase - previous.carrier_phase
        predicted = predicted_increment(previous.doppler, current.doppler, interval)
        residuals.append((current.epoch, measured - predicted))
    return tuple(residuals)


def detect_slips(
    observations: Sequence[Observation],
    *,
    threshold_cycles: float = SLIP_THRESHOLD_CYCLES,
) -> tuple[Slip, ...]:
    """Slips whose phase increment disagrees with the Doppler prediction."""
    if threshold_cycles <= 0:
        raise ValueError("threshold_cycles must be positive")
    by_prn: dict[int, list[Observation]] = {}
    for observation in observations:
        by_prn.setdefault(observation.prn, []).append(observation)
    slips = []
    for prn, group in sorted(by_prn.items()):
        for epoch, residual in doppler_residuals(group):
            if abs(residual) >= threshold_cycles:
                slips.append(Slip(prn=prn, epoch=epoch, cycles=residual))
    return tuple(slips)


def geometry_free(phase: DualFrequencyPhase) -> float:
    """Geometry-free carrier combination in metres."""
    # Convert cycles on each signal to metres before differencing. The shared
    # geometric range cancels in this combination, but atmospheric and phase
    # ambiguity effects can remain, so a jump is a diagnostic rather than proof.
    low = wavelength(phase.low_hz) * phase.low_cycles
    high = wavelength(phase.high_hz) * phase.high_cycles
    return low - high


def geometry_free_slips(
    phases: Sequence[DualFrequencyPhase],
    *,
    threshold_metres: float = GEOMETRY_FREE_THRESHOLD_METRES,
) -> tuple[GeometryFreeSlip, ...]:
    """Slips that jump the geometry-free combination by more than a metre bound."""
    if threshold_metres <= 0:
        raise ValueError("threshold_metres must be positive")
    by_prn: dict[int, list[DualFrequencyPhase]] = {}
    for phase in phases:
        by_prn.setdefault(phase.prn, []).append(phase)
    slips = []
    for prn, group in sorted(by_prn.items()):
        ordered = sorted(group, key=lambda phase: phase.epoch)
        combinations = [(phase.epoch, geometry_free(phase)) for phase in ordered]
        for (_, previous), (epoch, current) in pairwise(combinations):
            jump = current - previous
            if abs(jump) >= threshold_metres:
                slips.append(GeometryFreeSlip(prn=prn, epoch=epoch, metres=jump))
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
