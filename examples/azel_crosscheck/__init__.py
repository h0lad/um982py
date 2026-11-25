"""Checks azimuth and elevation from broadcast ephemerides against SATVIS2."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from examples.satellite_monitor import constellation_of
from um982py.experimental.orbit import (
    KeplerElements,
    SatelliteState,
    azimuth_elevation,
    state_from_record,
)
from um982py.gnss import WEEK_SECONDS
from um982py.messages import Record
from um982py.messages.enums import SatelliteSystem

DIRECTION_TOLERANCE_DEGREES = 2.0
ELEVATION_THRESHOLD_DEGREES = 10.0
GLONASS_EPOCH_MILLISECONDS = 1000.0
GPST_MINUS_BDT_SECONDS = 14.0
GLONASS_SLOT_OFFSET = 37

__all__ = [
    "DIRECTION_TOLERANCE_DEGREES",
    "ELEVATION_THRESHOLD_DEGREES",
    "AzimuthElevationDifference",
    "CrossCheckReport",
    "SatelliteGeometry",
    "cross_check",
    "galileo_elements",
    "native_number",
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
    def direction_error(self) -> float:
        """Angular separation in degrees, including at the zenith."""
        azimuth = math.radians(self.azimuth_error)
        computed = math.radians(self.computed.elevation)
        reported = math.radians(self.reported.elevation)
        half_chord_squared = (
            math.sin((computed - reported) / 2) ** 2
            + math.cos(computed) * math.cos(reported) * math.sin(azimuth / 2) ** 2
        )
        return math.degrees(2 * math.asin(math.sqrt(min(1.0, half_chord_squared))))

    @property
    def is_within_tolerance(self) -> bool:
        """True when the two lines of sight agree within the angular tolerance."""
        return self.direction_error <= DIRECTION_TOLERANCE_DEGREES


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

    @property
    def rms_direction_error(self) -> float:
        """Root-mean-square angular separation in degrees."""
        return _rms([difference.direction_error for difference in self.compared])

    def counts_agree(self, system: SatelliteSystem) -> bool:
        """True when every reported satellite of a system has an ephemeris."""
        return self.matched_counts.get(system, 0) == self.visibility_counts.get(
            system, 0
        )


def galileo_elements(record: Record) -> KeplerElements:
    """Convert a GALEPH record to the common Keplerian element type.

    The shared decoder selects the F/NAV or I/NAV clock polynomial and the
    matching broadcast group delay (Galileo OS SIS ICD).
    """
    return KeplerElements.from_record(record)


def native_number(system: SatelliteSystem, prn: int) -> int:
    """PRN in the system's own numbering; GLONASS wire numbers are slot + 37."""
    if system is SatelliteSystem.GLONASS and prn > GLONASS_SLOT_OFFSET:
        return prn - GLONASS_SLOT_OFFSET
    return prn


def prn_of(record: Record, system: SatelliteSystem) -> int:
    """Satellite number of an ephemeris record for its own system."""
    if system is SatelliteSystem.GLONASS:
        return record.integer("sloto")
    if system is SatelliteSystem.GALILEO:
        return record.integer("satid")
    return record.integer("prn")


def time_of_flight(record: Record, system: SatelliteSystem, epoch: float) -> float:
    """Seconds between an ephemeris reference time and the observation epoch.

    ``epoch`` is GPST seconds of week. BDSEPH ``toe`` is BDT seconds of week:
    it equals the broadcast value, for example 234000 s in IGS BRDC files,
    while BDSEPH ``week`` is the GPS week. The epoch therefore moves to
    BDT = GPST - 14 s before the subtraction.
    """
    if system is SatelliteSystem.GLONASS:
        difference = epoch - record.real("e_time") / GLONASS_EPOCH_MILLISECONDS
    elif system is SatelliteSystem.BEIDOU:
        difference = epoch - GPST_MINUS_BDT_SECONDS - record.real("toe")
    else:
        difference = epoch - record.real("toe")
    return (difference + 302400) % WEEK_SECONDS - 302400


_CONSTELLATION_CONSTANTS: dict[SatelliteSystem, str] = {
    SatelliteSystem.GALILEO: "GALILEO",
    SatelliteSystem.BEIDOU: "BEIDOU",
}


def satellite_state(
    record: Record, system: SatelliteSystem, epoch: float
) -> SatelliteState:
    """Propagate one broadcast ephemeris record with its own ICD constants."""
    propagation_time = time_of_flight(record, system, epoch)
    constellation = _CONSTELLATION_CONSTANTS.get(system, "GPS")
    return state_from_record(record, propagation_time, system=constellation)


def visibility_from_ephemerides(
    records_by_system: Mapping[SatelliteSystem, Sequence[Record]],
    observer: tuple[float, float, float],
    epoch: float,
) -> tuple[SatelliteGeometry, ...]:
    """Compute each satellite's geometry using the nearest bounded ephemeris."""
    nearest: dict[tuple[SatelliteSystem, int], tuple[float, Record]] = {}
    for system, records in records_by_system.items():
        max_age = 1800 if system is SatelliteSystem.GLONASS else 7200
        for record in records:
            key = system, prn_of(record, system)
            age = abs(time_of_flight(record, system, epoch))
            current = nearest.get(key)
            if age <= max_age and (current is None or age < current[0]):
                nearest[key] = age, record
    return tuple(
        SatelliteGeometry(
            system=system,
            prn=prn,
            azimuth=azimuth,
            elevation=elevation,
            range=slant_range,
        )
        for (system, prn), (_, record) in sorted(nearest.items())
        for azimuth, elevation, slant_range in (
            azimuth_elevation(satellite_state(record, system, epoch), observer),
        )
    )


def visibility_from_satvis(record: Record) -> tuple[SatelliteGeometry, ...]:
    """Decode one SATVIS2 frame into the receiver's reported geometry."""
    name = str(constellation_of(record))
    system = SatelliteSystem.__members__.get(name)
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


def _counts(satellites: Sequence[SatelliteGeometry]) -> dict[SatelliteSystem, int]:
    counts: dict[SatelliteSystem, int] = {}
    for satellite in satellites:
        counts[satellite.system] = counts.get(satellite.system, 0) + 1
    return dict(sorted(counts.items()))


def _rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))
