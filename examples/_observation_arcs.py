"""Continuity checks for RANGE carrier-phase observations."""

import math
from dataclasses import dataclass

from um982py.geodesy import wavelength


@dataclass(frozen=True, slots=True)
class CarrierState:
    """The signal and lock information needed to join two phase epochs."""

    epoch: float
    frequency_hz: float
    signal: int
    lock_seconds: float
    phase_cycles: float
    doppler_hz: float


def continuous(
    before: CarrierState,
    after: CarrierState,
    *,
    max_gap: float,
    phase_tolerance_m: float = 0.5,
) -> bool:
    """Require matching signals, advancing lock and Doppler-phase closure."""
    values = (
        before.epoch,
        after.epoch,
        before.frequency_hz,
        after.frequency_hz,
        before.lock_seconds,
        after.lock_seconds,
        before.phase_cycles,
        after.phase_cycles,
        before.doppler_hz,
        after.doppler_hz,
    )
    if not all(math.isfinite(value) for value in values):
        return False
    dt = after.epoch - before.epoch
    if (
        before.frequency_hz != after.frequency_hz
        or before.signal != after.signal
        or not 0 < dt <= max_gap
        or before.lock_seconds <= 0
        or after.lock_seconds < before.lock_seconds + dt - 0.02
    ):
        return False
    scale = wavelength(after.frequency_hz)
    observed = -(after.phase_cycles - before.phase_cycles) * scale
    predicted = -(before.doppler_hz + after.doppler_hz) * scale * dt / 2
    return abs(observed - predicted) <= phase_tolerance_m
