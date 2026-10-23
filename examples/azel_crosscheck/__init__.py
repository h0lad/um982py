"""Checks azimuth and elevation from broadcast ephemerides against SATVIS2."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from examples.ephemeris_orbit import (
    KeplerElements,
    SatelliteState,
    azimuth_elevation,
    orbit_state,
    state_from_record,
)
from examples.satellite_monitor import constellation_of
from um982py.messages import Record
from um982py.messages.enums import SatelliteSystem

AZIMUTH_TOLERANCE_DEGREES = 2.0
ELEVATION_TOLERANCE_DEGREES = 2.0
ELEVATION_THRESHOLD_DEGREES = 10.0
GLONASS_EPOCH_MILLISECONDS = 1000.0

__all__ = [
    "AZIMUTH_TOLERANCE_DEGREES",
    "ELEVATION_THRESHOLD_DEGREES",
    "ELEVATION_TOLERANCE_DEGREES",
    "AzimuthElevationDifference",
    "CrossCheckReport",
    "SatelliteGeometry",
    "cross_check",
    "galileo_elements",
    "prn_of",
    "satellite_state",
    "time_of_flight",
    "visibility_from_ephemerides",
    "visibility_from_satvis",
]


@dataclass(frozen=True, slots=True)
class SatelliteGeometry:
    """Azimuth, elevation in degrees and slant range in metres."""

    system: SatelliteSystem
    prn: int
    azimuth: float
    elevation: float
    range: float


@dataclass(frozen=True, slots=True)
class AzimuthElevationDifference:
    """Computed versus reported geometry of one satellite."""

    system: SatelliteSystem
    prn: int
    computed: SatelliteGeometry
    reported: SatelliteGeometry

    @property
    def azimuth_error(self) -> float:
        """Absolute azimuth difference in degrees, wrapped to 0..180."""
        difference = (
            self.computed.azimuth - self.reported.azimuth + 180.0
        ) % 360.0 - 180.0
        return abs(difference)

    @property
    def elevation_error(self) -> float:
        """Absolute elevation difference in degrees."""
        return abs(self.computed.elevation - self.reported.elevation)

    @property
    def is_within_tolerance(self) -> bool:
        """True when both differences meet the stated tolerances."""
        return (
            self.azimuth_error <= AZIMUTH_TOLERANCE_DEGREES
            and self.elevation_error <= ELEVATION_TOLERANCE_DEGREES
        )


@dataclass(frozen=True, slots=True)
class CrossCheckReport:
    """Per-satellite geometry differences and the counts behind them."""

    epoch: float
    computed: tuple[SatelliteGeometry, ...]
    compared: tuple[AzimuthElevationDifference, ...]
    visibility_counts: Mapping[SatelliteSystem, int]
    ephemeris_counts: Mapping[SatelliteSystem, int]
    matched_counts: Mapping[SatelliteSystem, int]

    @property
    def rms_azimuth_error(self) -> float:
        """Root-mean-square azimuth difference in degrees."""
        return _rms([difference.azimuth_error for difference in self.compared])

    @property
    def rms_elevation_error(self) -> float:
        """Root-mean-square elevation difference in degrees."""
        return _rms([difference.elevation_error for difference in self.compared])

    def counts_agree(self, system: SatelliteSystem) -> bool:
        """True when every reported satellite of a system has an ephemeris."""
        return self.matched_counts.get(system, 0) == self.visibility_counts.get(
            system, 0
        )


def galileo_elements(record: Record) -> KeplerElements:
    """Convert a GALEPH record to the common Keplerian element type."""
    return KeplerElements(
        semi_major_axis=record.real("roota") ** 2,
        eccentricity=record.real("ecc"),
        mean_anomaly=record.real("m0"),
        argument_of_perigee=record.real("omega"),
        inclination=record.real("i0"),
        right_ascension=record.real("omega0"),
        delta_n=record.real("deltan"),
        idot=record.real("idot"),
        omega_dot=record.real("omegadot"),
        cuc=record.real("cuc"),
        cus=record.real("cus"),
        crc=record.real("crc"),
        crs=record.real("crs"),
        cic=record.real("cic"),
        cis=record.real("cis"),
        toe=record.real("toe"),
        af0=record.real("fnavaf0"),
        af1=record.real("fnavaf1"),
        af2=record.real("fnavaf2"),
        tgd=record.real("e1e5abgd"),
    )


def prn_of(record: Record, system: SatelliteSystem) -> int:
    """Satellite number of an ephemeris record for its own system."""
    if system is SatelliteSystem.GLONASS:
        return record.integer("sloto")
    if system is SatelliteSystem.GALILEO:
        return record.integer("satid")
    return record.integer("prn")


def time_of_flight(record: Record, system: SatelliteSystem, epoch: float) -> float:
    """Seconds between an ephemeris reference time and the observation epoch."""
    if system is SatelliteSystem.GLONASS:
        difference = epoch - record.real("e_time") / GLONASS_EPOCH_MILLISECONDS
    else:
        difference = epoch - record.real("toe")
    return (difference + 302400) % 604800 - 302400


def satellite_state(
    record: Record, system: SatelliteSystem, epoch: float
) -> SatelliteState:
    """Propagate one broadcast ephemeris record to the observation epoch."""
    propagation_time = time_of_flight(record, system, epoch)
    if system is SatelliteSystem.GALILEO:
        return orbit_state(galileo_elements(record), propagation_time)
    return state_from_record(record, propagation_time)


def visibility_from_ephemerides(
    records_by_system: Mapping[SatelliteSystem, Sequence[Record]],
    observer: tuple[float, float, float],
    epoch: float,
) -> tuple[SatelliteGeometry, ...]:
    """Compute the geometry of every satellite that has an ephemeris record."""
    return tuple(
        SatelliteGeometry(
            system=system,
            prn=prn_of(record, system),
            azimuth=azimuth,
            elevation=elevation,
            range=slant_range,
        )
        for system in sorted(records_by_system)
        for record in records_by_system[system]
        for azimuth, elevation, slant_range in (
            azimuth_elevation(satellite_state(record, system, epoch), observer),
        )
    )


def visibility_from_satvis(record: Record) -> tuple[SatelliteGeometry, ...]:
    """Decode one SATVIS2 frame into the receiver's reported geometry."""
    name = str(constellation_of(record))
    system = _SYSTEM_NAMES.get(name)
    if system is None:
        return ()
    return tuple(
        SatelliteGeometry(
            system=system,
            prn=satellite.integer("prn"),
            azimuth=satellite.real("azimuth"),
            elevation=satellite.real("elevation"),
            range=0.0,
        )
        for satellite in record.records("satellites")
    )


def cross_check(
    records_by_system: Mapping[SatelliteSystem, Sequence[Record]],
    satvis_records: Sequence[Record],
    observer: tuple[float, float, float],
    epoch: float,
    *,
    minimum_elevation: float = ELEVATION_THRESHOLD_DEGREES,
) -> CrossCheckReport:
    """Join ephemeris geometry and SATVIS2 on constellation and PRN."""
    computed = visibility_from_ephemerides(records_by_system, observer, epoch)
    reported = tuple(
        satellite
        for record in satvis_records
        for satellite in visibility_from_satvis(record)
    )
    computed_by_key = {(item.system, item.prn): item for item in computed}
    reported_by_key = {(item.system, item.prn): item for item in reported}
    differences = tuple(
        AzimuthElevationDifference(
            system=key[0],
            prn=key[1],
            computed=computed_by_key[key],
            reported=item,
        )
        for key, item in sorted(reported_by_key.items())
        if key in computed_by_key and item.elevation >= minimum_elevation
    )
    visibility_counts = _counts(reported)
    ephemeris_counts = _counts(computed)
    matched_counts = _counts(
        [item for item in reported if (item.system, item.prn) in computed_by_key]
    )
    return CrossCheckReport(
        epoch=epoch,
        computed=computed,
        compared=differences,
        visibility_counts=MappingProxyType(visibility_counts),
        ephemeris_counts=MappingProxyType(ephemeris_counts),
        matched_counts=MappingProxyType(matched_counts),
    )


_SYSTEM_NAMES: Mapping[str, SatelliteSystem] = {
    "GPS": SatelliteSystem.GPS,
    "GLONASS": SatelliteSystem.GLONASS,
    "GALILEO": SatelliteSystem.GALILEO,
    "BEIDOU": SatelliteSystem.BEIDOU,
    "QZSS": SatelliteSystem.QZSS,
    "SBAS": SatelliteSystem.SBAS,
    "NAVIC": SatelliteSystem.IRNSS,
    "IRNSS": SatelliteSystem.IRNSS,
}


def _counts(satellites: Sequence[SatelliteGeometry]) -> dict[SatelliteSystem, int]:
    counts: dict[SatelliteSystem, int] = {}
    for satellite in satellites:
        counts[satellite.system] = counts.get(satellite.system, 0) + 1
    return dict(sorted(counts.items()))


def _rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))
