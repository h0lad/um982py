"""Fits an empirical C/N0 elevation pattern from receiver observations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from examples.satellite_monitor import Constellation as SkyConstellation
from um982py.capture import gps_signals, record_epoch
from um982py.geodesy import records_from
from um982py.messages import Record, Value
from um982py.stats import _least_squares, percentile

MINIMUM_SAMPLES = 4
DEFAULT_CURVE_STEP = 5.0

__all__ = [
    "DEFAULT_CURVE_STEP",
    "MINIMUM_SAMPLES",
    "Constellation",
    "GainFit",
    "SkySample",
    "constellation_of",
    "epoch_sky_samples",
    "fit_gain_pattern",
    "gain_curve",
    "sky_samples",
]


class Constellation(StrEnum):
    """Satellite constellation as named in an ASCII SATVIS2 frame."""

    GPS = "GPS"
    GLONASS = "GLONASS"
    GALILEO = "GALILEO"
    BEIDOU = "BEIDOU"
    QZSS = "QZSS"
    SBAS = "SBAS"
    NAVIC = "NAVIC"


@dataclass(frozen=True, slots=True)
class SkySample:
    """One satellite joined from a visibility frame and a RANGE observation."""

    prn: int
    constellation: Constellation
    elevation: float
    """Elevation above the horizon in degrees."""
    azimuth: float
    """Azimuth from north in degrees."""
    cn0: float
    """Strongest reported C/N0 of the satellite in dB-Hz."""
    range: float
    """Geometric range in metres, taken from the pseudorange of that signal."""


@dataclass(frozen=True, slots=True)
class GainFit:
    zenith_cn0: float
    linear_rolloff: float
    quadratic_rolloff: float
    reference_range: float
    residual_rms_db: float
    sample_count: int

    def gain(self, elevation: float) -> float:
        unit = 1.0 - math.sin(math.radians(elevation))
        return self.linear_rolloff * unit + self.quadratic_rolloff * unit * unit

    def cn0(self, elevation: float) -> float:
        """Fitted C/N0 in dB-Hz at the reference range for an elevation."""
        return self.zenith_cn0 + self.gain(elevation)


_SYSTEM_CONSTELLATIONS: dict[int, Constellation] = {
    0: Constellation.GPS,
    1: Constellation.GLONASS,
    2: Constellation.SBAS,
    3: Constellation.GALILEO,
    4: Constellation.BEIDOU,
    5: Constellation.QZSS,
    6: Constellation.NAVIC,
}


def constellation_of(value: Value) -> Constellation:
    """Constellation of a SATVIS2 frame, which must name it in ASCII form."""
    if isinstance(value, int):
        value = SkyConstellation.from_value(value).value
    if not isinstance(value, str):
        raise ValueError("SATVIS2 frame does not name its constellation")
    try:
        return Constellation(value)
    except ValueError:
        raise ValueError(f"unknown constellation {value}") from None


def _strongest_signals(
    record: Record, *, system: int = 0, signal: int = 0
) -> dict[int, tuple[float, float]]:
    """Strongest C/N0 and its pseudorange per PRN of one RANGE record."""
    strongest: dict[int, tuple[float, float]] = {}
    if system == 0 and signal == 0:
        observations = [
            observation
            for observation, _ in gps_signals(record, [1575.42e6], phase=False)
        ]
    else:
        observations = [
            observation
            for observation in records_from(record, "observations")
            if (observation.integer("tracking_status") >> 16) & 7 == system
            and (observation.integer("tracking_status") >> 21) & 31 == signal
            and bool(observation.integer("tracking_status") & (1 << 12))
        ]
    for observation in observations:
        prn = observation.integer("prn")
        candidate = (observation.real("cn0"), observation.real("pseudorange"))
        if prn not in strongest or candidate[0] > strongest[prn][0]:
            strongest[prn] = candidate
    return strongest


def _visibility(
    records: Sequence[Record],
    *,
    constellation: Constellation = Constellation.GPS,
) -> dict[int, tuple[Constellation, float, float]]:
    """PRNs seen once in the epoch, with the constellation and geometry of each."""
    visible: dict[int, list[tuple[Constellation, float, float]]] = {}
    for record in records:
        current = constellation_of(record["constellation"])
        if current is not constellation:
            continue
        for satellite in records_from(record, "satellites"):
            visible.setdefault(satellite.integer("prn"), []).append(
                (
                    current,
                    satellite.real("elevation"),
                    satellite.real("azimuth"),
                )
            )
    return {prn: entries[0] for prn, entries in visible.items() if len(entries) == 1}


def sky_samples(
    visibility: Sequence[Record],
    observations: Record,
    *,
    system: int = 0,
    signal: int = 0,
) -> tuple[SkySample, ...]:
    """Join one visibility epoch to one RANGE epoch by PRN, dropping ambiguous PRNs."""
    if system not in _SYSTEM_CONSTELLATIONS:
        raise ValueError("system must be in 0..6")
    visible = _visibility(visibility, constellation=_SYSTEM_CONSTELLATIONS[system])
    strongest = _strongest_signals(observations, system=system, signal=signal)
    return tuple(
        SkySample(
            prn=prn,
            constellation=constellation,
            elevation=elevation,
            azimuth=azimuth,
            cn0=strongest[prn][0],
            range=strongest[prn][1],
        )
        for prn, (constellation, elevation, azimuth) in sorted(visible.items())
        if prn in strongest
    )


def _epoch_frames(visibility: Sequence[Record]) -> list[list[Record]]:
    """Split visibility frames into epochs at every repeated constellation."""
    epochs: list[list[Record]] = []
    current: list[Record] = []
    seen: set[str] = set()
    for record in visibility:
        name = str(record["constellation"])
        if name in seen:
            epochs.append(current)
            current, seen = [], set()
        current.append(record)
        seen.add(name)
    if current:
        epochs.append(current)
    return epochs


def epoch_sky_samples(
    visibility: Sequence[Record],
    observations: Sequence[Record],
    *,
    system: int = 0,
    signal: int = 0,
) -> tuple[SkySample, ...]:
    """Samples of every epoch, grouping the per-constellation visibility frames."""
    epochs: dict[float, list[Record]] = {}
    for record in visibility:
        epochs.setdefault(record_epoch(record), []).append(record)
    return tuple(
        sample
        for record in observations
        for sample in sky_samples(
            epochs.get(record_epoch(record), ()),
            record,
            system=system,
            signal=signal,
        )
    )


def fit_gain_pattern(samples: Sequence[SkySample]) -> GainFit:
    if len(samples) < MINIMUM_SAMPLES:
        raise ValueError(f"at least {MINIMUM_SAMPLES} samples are required")
    reference = percentile([sample.range for sample in samples], 0.5)
    if reference <= 0:
        raise ValueError("range must be positive")
    units = [1.0 - math.sin(math.radians(sample.elevation)) for sample in samples]
    design = [[1.0, unit, unit * unit] for unit in units]
    values = [
        sample.cn0 + 20.0 * math.log10(sample.range / reference) for sample in samples
    ]
    coefficients = _least_squares(design, values)
    residuals = [
        value - sum(c * x for c, x in zip(coefficients, row, strict=True))
        for value, row in zip(values, design, strict=True)
    ]
    return GainFit(
        zenith_cn0=coefficients[0],
        linear_rolloff=coefficients[1],
        quadratic_rolloff=coefficients[2],
        reference_range=reference,
        residual_rms_db=math.sqrt(
            sum(residual * residual for residual in residuals) / len(residuals)
        ),
        sample_count=len(samples),
    )


def gain_curve(
    fit: GainFit, step: float = DEFAULT_CURVE_STEP
) -> tuple[tuple[float, float, float], ...]:
    """Elevation in degrees, gain in dB and C/N0 in dB-Hz at every ``step``."""
    if step <= 0 or step > 90 or not math.isclose(90.0 % step, 0.0, abs_tol=1e-9):
        raise ValueError("step must divide 90 degrees")
    count = round(90.0 / step)
    return tuple(
        (
            index * step,
            fit.gain(index * step),
            fit.cn0(index * step),
        )
        for index in range(count + 1)
    )
