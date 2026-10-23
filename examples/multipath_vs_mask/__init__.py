"""Sweeps elevation masks for multipath and checks receiver state."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from examples.multipath_analysis import (
    MultipathSeries,
    Observation,
    multipath_series,
    rms,
)
from um982py.experimental import LogList
from um982py.geodesy import records_from, wavelength
from um982py.messages.record import Record

CARRIER_HZ = 1575.42e6
ZENITH_MULTIPATH_METRES = 0.5
GEOMETRY_METRES = 22_000_000.0
LOWEST_ELEVATION = 0.5
MONOTONIC_TOLERANCE = 1e-12
SAMPLES_PER_PERIOD = 4


@dataclass(frozen=True, slots=True)
class SkySignal:
    """Injected code multipath amplitude of one satellite at a fixed elevation."""

    prn: int
    elevation: float
    amplitude: float

    @classmethod
    def at_elevation(
        cls,
        prn: int,
        elevation: float,
        *,
        zenith_amplitude: float = ZENITH_MULTIPATH_METRES,
    ) -> SkySignal:
        """Signal whose multipath amplitude follows the inverse-sine model."""
        return cls(
            prn=prn,
            elevation=elevation,
            amplitude=multipath_amplitude(elevation, zenith_amplitude=zenith_amplitude),
        )


@dataclass(frozen=True, slots=True)
class ElevatedSeries:
    """Detrended code-minus-carrier residuals of one satellite and its elevation."""

    elevation: float
    series: MultipathSeries


@dataclass(frozen=True, slots=True)
class MaskStep:
    """Pooled multipath RMS of the signals kept at one elevation mask."""

    mask_degrees: float
    signals: int
    rms: float


@dataclass(frozen=True, slots=True)
class ReceiverState:
    """Configuration, mode, masks and active logs of a receiver."""

    configuration: tuple[bytes, ...]
    mode: tuple[str, ...]
    masks: tuple[tuple[str, ...], ...]
    logs: LogList

    @classmethod
    def from_parts(cls, parts: tuple[object, ...]) -> ReceiverState:
        """Build a state from the four values of ``receiver_state``."""
        configuration, mode, masks, logs = parts
        if not isinstance(logs, LogList):
            raise ValueError("the fourth state part is not a log list")
        return cls(
            configuration=cast("tuple[bytes, ...]", configuration),
            mode=cast("tuple[str, ...]", mode),
            masks=cast("tuple[tuple[str, ...], ...]", masks),
            logs=logs,
        )


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """Which parts of the receiver state changed across a sweep."""

    identical: bool
    changed: tuple[str, ...]


def multipath_amplitude(
    elevation: float, *, zenith_amplitude: float = ZENITH_MULTIPATH_METRES
) -> float:
    """Injected code multipath amplitude in metres at an elevation in degrees."""
    if not LOWEST_ELEVATION <= elevation <= 90.0:
        raise ValueError(f"elevation must be in {LOWEST_ELEVATION}..90 degrees")
    return zenith_amplitude / math.sin(math.radians(elevation))


def synthetic_observations(
    signals: Sequence[SkySignal], *, period: float, samples: int
) -> tuple[Observation, ...]:
    """RANGE observations of the injected sinusoids at four samples per period."""
    if not period > 0:
        raise ValueError("period must be positive")
    if samples <= 1:
        raise ValueError("at least two samples are required")
    cadence = period / SAMPLES_PER_PERIOD
    carrier_wavelength = wavelength(CARRIER_HZ)
    return tuple(
        Observation(
            prn=signal.prn,
            epoch=index * cadence,
            frequency_hz=CARRIER_HZ,
            pseudorange=GEOMETRY_METRES
            + signal.amplitude * math.sin(2 * math.pi * index / SAMPLES_PER_PERIOD),
            carrier_phase=-GEOMETRY_METRES / carrier_wavelength,
        )
        for signal in signals
        for index in range(samples)
    )


def elevated_series(
    observations: Sequence[Observation], elevations: Mapping[int, float]
) -> tuple[ElevatedSeries, ...]:
    """Pair the code-minus-carrier series of every signal with its elevation."""
    return tuple(
        ElevatedSeries(elevation=elevations[item.prn], series=item)
        for item in multipath_series(observations)
        if item.prn in elevations
    )


def _first_epoch(records: Sequence[Record]) -> tuple[Record, ...]:
    seen = set()
    epoch = []
    for record in records:
        constellation = str(record["constellation"])
        if constellation in seen:
            break
        seen.add(constellation)
        epoch.append(record)
    return tuple(epoch)


def unambiguous_elevations(records: Sequence[Record]) -> dict[int, float]:
    """Elevation per PRN of the earliest SATVIS2 epoch, dropping shared PRNs."""
    by_constellation: dict[str, dict[int, float]] = {}
    for record in _first_epoch(records):
        satellites = by_constellation.setdefault(str(record["constellation"]), {})
        for satellite in records_from(record, "satellites"):
            satellites.setdefault(satellite.integer("prn"), satellite.real("elevation"))
    systems: dict[int, int] = {}
    for satellites in by_constellation.values():
        for prn in satellites:
            systems[prn] = systems.get(prn, 0) + 1
    return {
        prn: elevation
        for satellites in by_constellation.values()
        for prn, elevation in satellites.items()
        if systems[prn] == 1
    }


def kept(
    series: Sequence[ElevatedSeries], mask_degrees: float
) -> tuple[ElevatedSeries, ...]:
    """Signals at or above an elevation mask in degrees."""
    return tuple(item for item in series if item.elevation >= mask_degrees)


def pooled_rms(series: Sequence[ElevatedSeries]) -> float:
    """Root mean square over every residual of the given signals in metres."""
    return rms([value for item in series for value in item.series.residuals])


def mask_step(mask_degrees: float, series: Sequence[ElevatedSeries]) -> MaskStep:
    """Multipath statistics after removing the signals below one mask."""
    visible = kept(series, mask_degrees)
    return MaskStep(
        mask_degrees=mask_degrees, signals=len(visible), rms=pooled_rms(visible)
    )


def mask_sweep(
    series: Sequence[ElevatedSeries], masks: Sequence[float]
) -> tuple[MaskStep, ...]:
    """One mask step per requested elevation, in ascending mask order."""
    return tuple(mask_step(mask, series) for mask in sorted(masks))


def is_falling(
    steps: Sequence[MaskStep], *, tolerance: float = MONOTONIC_TOLERANCE
) -> bool:
    """True when the pooled RMS never rises by more than ``tolerance`` metres."""
    return all(
        before.rms + tolerance >= after.rms
        for before, after in itertools.pairwise(steps)
    )


def mask_degrees(state: ReceiverState) -> float:
    """Elevation mask in degrees reported by the CONFIG MASK record of a state."""
    for fields in state.masks:
        if fields[:1] == ("MASK",) and len(fields) > 1:
            return float(fields[1].split()[-1])
    raise ValueError("state carries no CONFIG MASK record")


def verify_restore(before: ReceiverState, after: ReceiverState) -> RestoreReport:
    """Compare the configuration, mode, masks and logs of two snapshots."""
    changed = tuple(
        name
        for name, left, right in (
            ("configuration", before.configuration, after.configuration),
            ("mode", before.mode, after.mode),
            ("masks", before.masks, after.masks),
            ("logs", before.logs, after.logs),
        )
        if left != right
    )
    return RestoreReport(identical=not changed, changed=changed)
