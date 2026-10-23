"""Measures code-minus-carrier multipath from RANGE observations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.geodesy import wavelength
from um982py.stats import detrend

GPS_L1_HZ = 1575.42e6
DETREND_ORDER = 1


@dataclass(frozen=True, slots=True)
class Observation:
    """Pseudorange in metres and carrier phase in cycles at one epoch."""

    prn: int
    epoch: float
    frequency_hz: float
    pseudorange: float
    carrier_phase: float


@dataclass(frozen=True, slots=True)
class MultipathSeries:
    """Detrended code-minus-carrier residual in metres of one satellite signal."""

    prn: int
    frequency_hz: float
    epochs: tuple[float, ...]
    residuals: tuple[float, ...]
    rms: float


@dataclass(frozen=True, slots=True)
class EpochSummary:
    """Detrended code-minus-carrier residual of every satellite at one epoch."""

    epoch: float
    signals: int
    rms: float
    maximum: float


def code_minus_carrier(
    pseudorange: float, carrier_phase: float, frequency_hz: float
) -> float:
    """Code minus carrier in metres, with the phase sign of the RANGE log."""
    return pseudorange + wavelength(frequency_hz) * carrier_phase


def multipath_series(
    observations: Sequence[Observation], *, order: int = DETREND_ORDER
) -> tuple[MultipathSeries, ...]:
    """Residual of the detrended code-minus-carrier combination per signal."""
    groups: dict[tuple[int, float], list[Observation]] = {}
    for observation in observations:
        groups.setdefault((observation.prn, observation.frequency_hz), []).append(
            observation
        )
    series = []
    for (prn, frequency_hz), group in sorted(groups.items()):
        ordered = sorted(group, key=lambda observation: observation.epoch)
        epochs = [observation.epoch for observation in ordered]
        values = [
            code_minus_carrier(
                observation.pseudorange,
                observation.carrier_phase,
                observation.frequency_hz,
            )
            for observation in ordered
        ]
        if len(values) <= order + 1:
            continue
        residuals = detrend(epochs, values, order)
        series.append(
            MultipathSeries(
                prn=prn,
                frequency_hz=frequency_hz,
                epochs=tuple(epochs),
                residuals=tuple(residuals),
                rms=rms(residuals),
            )
        )
    return tuple(series)


def rms(values: Sequence[float]) -> float:
    """Root mean square of a residual series in metres."""
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def epoch_summaries(series: Sequence[MultipathSeries]) -> tuple[EpochSummary, ...]:
    """Residual statistics across all signals for every epoch."""
    by_epoch: dict[float, list[float]] = {}
    for item in series:
        for epoch, residual in zip(item.epochs, item.residuals, strict=True):
            by_epoch.setdefault(epoch, []).append(residual)
    return tuple(
        EpochSummary(
            epoch=epoch,
            signals=len(residuals),
            rms=rms(residuals),
            maximum=max(abs(residual) for residual in residuals),
        )
        for epoch, residuals in sorted(by_epoch.items())
    )
