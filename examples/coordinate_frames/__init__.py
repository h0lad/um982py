"""Converts between ECEF, geodetic and ENU frames and baselines."""

from __future__ import annotations

import math
from dataclasses import dataclass

from um982py.geodesy import ecef_from_geodetic, enu_from_ecef, geodetic_from_ecef
from um982py.messages.record import Record


@dataclass(frozen=True, slots=True)
class Geodetic:
    """Latitude and longitude in degrees with ellipsoidal height in metres."""

    latitude: float
    longitude: float
    height: float

    def ecef(self) -> tuple[float, float, float]:
        """Earth-centred position in metres."""
        return ecef_from_geodetic(self.latitude, self.longitude, self.height)

    @classmethod
    def from_ecef(cls, x: float, y: float, z: float) -> Geodetic:
        """Geodetic position of an Earth-centred point in metres."""
        return cls(*geodetic_from_ecef(x, y, z))

    @classmethod
    def from_position_record(cls, record: Record) -> Geodetic:
        """Position of a decoded BESTXYZ frame."""
        return cls.from_ecef(record.real("p_x"), record.real("p_y"), record.real("p_z"))


@dataclass(frozen=True, slots=True)
class Baseline:
    """Baseline vector in local east, north and up metres."""

    east: float
    north: float
    up: float

    @property
    def length(self) -> float:
        """Straight-line baseline length in metres."""
        return math.sqrt(self.east**2 + self.north**2 + self.up**2)

    @property
    def azimuth(self) -> float:
        """Return azimuth clockwise from north in degrees, or zero for a null vector."""
        return math.degrees(math.atan2(self.east, self.north)) % 360.0

    @property
    def elevation(self) -> float:
        """Baseline elevation angle in degrees above the local horizon."""
        return math.degrees(math.atan2(self.up, math.hypot(self.east, self.north)))

    @classmethod
    def between(cls, origin: Geodetic, target: Geodetic) -> Baseline:
        """Baseline from ``origin`` to ``target`` in the local frame of ``origin``."""
        x, y, z = origin.ecef()
        target_x, target_y, target_z = target.ecef()
        return cls.from_ecef((target_x - x, target_y - y, target_z - z), origin=origin)

    @classmethod
    def from_ecef(
        cls, delta: tuple[float, float, float], *, origin: Geodetic
    ) -> Baseline:
        """Baseline from an Earth-centred difference rotated into the origin frame."""
        east, north, up = enu_from_ecef(
            delta[0], delta[1], delta[2], origin.latitude, origin.longitude
        )
        return cls(east, north, up)

    @classmethod
    def from_baseline_record(cls, record: Record) -> Baseline:
        """Baseline of a decoded BSLNENUHD frame."""
        return cls(
            east=record.real("delta_1"),
            north=record.real("delta_2"),
            up=record.real("delta_3"),
        )


def enu_to_ecef(
    east: float, north: float, up: float, latitude: float, longitude: float
) -> tuple[float, float, float]:
    """Rotate local east, north and up metres into Earth-centred axes."""
    phi, lam = math.radians(latitude), math.radians(longitude)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    sin_lam, cos_lam = math.sin(lam), math.cos(lam)
    x = -sin_lam * east - sin_phi * cos_lam * north + cos_phi * cos_lam * up
    y = cos_lam * east - sin_phi * sin_lam * north + cos_phi * sin_lam * up
    z = cos_phi * north + sin_phi * up
    return x, y, z


def antenna_position(origin: Geodetic, baseline: Baseline) -> Geodetic:
    """Second antenna position from the first antenna and the reported baseline."""
    x, y, z = origin.ecef()
    delta_x, delta_y, delta_z = enu_to_ecef(
        baseline.east, baseline.north, baseline.up, origin.latitude, origin.longitude
    )
    return Geodetic.from_ecef(x + delta_x, y + delta_y, z + delta_z)


def round_trip_baseline(origin: Geodetic, baseline: Baseline) -> Baseline:
    """Baseline re-derived from the antenna position that ``baseline`` implies."""
    return Baseline.between(origin, antenna_position(origin, baseline))
