"""Sizes the relativistic satellite clock term and its effect on a position."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from examples.wls_position import PositionSolution, RangeMeasurement
from um982py.experimental.orbit import (
    ORBIT_CONSTANTS,
    KeplerElements,
    relativistic_correction,
    system_of,
)
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef
from um982py.gnss import SPEED_OF_LIGHT
from um982py.messages.record import Record


@dataclass(frozen=True, slots=True)
class OrbitTerm:
    """The eccentricity term of one broadcast orbit."""

    system: str
    prn: int
    eccentricity: float
    amplitude_ns: float
    amplitude_m: float


def orbit_term(record: Record) -> OrbitTerm:
    """Peak of F e sqrt(A) sin E, reached a quarter orbit from perigee."""
    system = system_of(record)
    elements = KeplerElements.from_record(record)
    peak = abs(
        relativistic_correction(elements, math.pi / 2, mu=ORBIT_CONSTANTS[system][0])
    )
    prn = record.integer("satid" if "satid" in record else "prn")
    return OrbitTerm(
        system,
        prn,
        elements.eccentricity,
        peak * 1e9,
        peak * SPEED_OF_LIGHT,
    )


def without_relativity(
    measurements: Sequence[RangeMeasurement],
) -> tuple[RangeMeasurement, ...]:
    """The same ranges with the eccentricity term left out of the clocks."""
    return tuple(
        replace(
            item,
            satellite_clock=item.satellite_clock - item.relativity,
            relativity=0.0,
        )
        for item in measurements
    )


@dataclass(frozen=True, slots=True)
class PositionShift:
    """East, north and up displacement and receiver clock change."""

    east_m: float
    north_m: float
    up_m: float
    clock_m: float

    @property
    def horizontal_m(self) -> float:
        return math.hypot(self.east_m, self.north_m)

    @property
    def three_d_m(self) -> float:
        return math.hypot(self.east_m, self.north_m, self.up_m)


def position_shift(
    reference: PositionSolution, other: PositionSolution
) -> PositionShift:
    """Displacement of ``other`` from ``reference`` in the local frame."""
    latitude, longitude, _ = geodetic_from_ecef(reference.x, reference.y, reference.z)
    east, north, up = enu_from_ecef(
        other.x - reference.x,
        other.y - reference.y,
        other.z - reference.z,
        latitude,
        longitude,
    )
    return PositionShift(
        east,
        north,
        up,
        (other.clock_bias - reference.clock_bias) * SPEED_OF_LIGHT,
    )
