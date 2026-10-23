"""WGS84 geodesy helpers shared by library and examples."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.messages import Record

__all__ = [
    "SPEED_OF_LIGHT",
    "WGS84_A",
    "WGS84_E2",
    "WGS84_F",
    "dms_to_degrees",
    "ecef_from_geodetic",
    "elevation_mask_filter",
    "enu_from_ecef",
    "geodetic_from_ecef",
    "haversine_distance",
    "receiver_ecef",
    "records_from",
    "wavelength",
]

SPEED_OF_LIGHT = 299_792_458.0

WGS84_A = 6_378_137.0


WGS84_F = 1 / 298.257_223_563


WGS84_E2 = WGS84_F * (2 - WGS84_F)


def dms_to_degrees(value: float) -> float:
    """Convert a Unicore DDMM.MMMM / DDDMM.MMMM field to signed degrees."""
    if not math.isfinite(value):
        raise ValueError("coordinate must be finite")
    sign = -1.0 if value < 0 else 1.0
    value = abs(value)
    degrees = int(value // 100)
    minutes = value - degrees * 100
    if minutes >= 60:
        raise ValueError("coordinate minutes must be less than 60")
    return sign * (degrees + minutes / 60)


def haversine_distance(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Great-circle distance in metres between two WGS84 positions."""
    coordinates = (latitude_a, longitude_a, latitude_b, longitude_b)
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("coordinates must be finite")
    if not (-90 <= latitude_a <= 90 and -90 <= latitude_b <= 90):
        raise ValueError("latitude must be in -90..90 degrees")
    if not (-180 <= longitude_a <= 180 and -180 <= longitude_b <= 180):
        raise ValueError("longitude must be in -180..180 degrees")
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    h = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(h)))


def ecef_from_geodetic(
    latitude: float, longitude: float, height: float
) -> tuple[float, float, float]:
    """Convert geodetic degrees and ellipsoidal height to ECEF metres."""
    if not all(math.isfinite(value) for value in (latitude, longitude, height)):
        raise ValueError("coordinates must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("geodetic coordinates out of range")
    phi, lam = math.radians(latitude), math.radians(longitude)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_phi * sin_phi)
    x = (n + height) * cos_phi * math.cos(lam)
    y = (n + height) * cos_phi * math.sin(lam)
    z = (n * (1 - WGS84_E2) + height) * sin_phi
    return x, y, z


def geodetic_from_ecef(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert ECEF metres to geodetic degrees and ellipsoidal height."""
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise ValueError("ECEF coordinates must be finite")
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    # Longitude is arbitrary at the poles, and the iteration divides by cos(phi).
    if p < 1e-9:
        if abs(z) < 1e-9:
            raise ValueError("geodetic coordinates are undefined at Earth's centre")
        polar_radius = WGS84_A * (1 - WGS84_F)
        return math.copysign(90.0, z), 0.0, abs(z) - polar_radius
    phi = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(8):
        sin_phi = math.sin(phi)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_phi * sin_phi)
        height = p / math.cos(phi) - n
        phi = math.atan2(z, p * (1 - WGS84_E2 * n / (n + height)))
    sin_phi = math.sin(phi)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_phi * sin_phi)
    return math.degrees(phi), math.degrees(lon), p / math.cos(phi) - n


def enu_from_ecef(
    x: float,
    y: float,
    z: float,
    latitude: float,
    longitude: float,
) -> tuple[float, float, float]:
    """Rotate an ECEF vector into local east, north, up metres."""
    phi, lam = math.radians(latitude), math.radians(longitude)
    dx, dy, dz = x, y, z
    east = -math.sin(lam) * dx + math.cos(lam) * dy
    north = (
        -math.sin(phi) * math.cos(lam) * dx
        - math.sin(phi) * math.sin(lam) * dy
        + math.cos(phi) * dz
    )
    up = (
        math.cos(phi) * math.cos(lam) * dx
        + math.cos(phi) * math.sin(lam) * dy
        + math.sin(phi) * dz
    )
    return east, north, up


def wavelength(frequency_hz: float) -> float:
    """Carrier wavelength in metres for a finite, positive frequency."""
    if (
        isinstance(frequency_hz, bool)
        or not math.isfinite(frequency_hz)
        or frequency_hz <= 0
    ):
        raise ValueError("frequency must be finite and positive")
    return SPEED_OF_LIGHT / frequency_hz


def elevation_mask_filter(
    satellites: Iterable[Record], minimum_elevation: float
) -> list[Record]:
    """Keep satellites at or above an elevation in degrees."""
    return [
        satellite
        for satellite in satellites
        if float(satellite.real("elevation")) >= minimum_elevation
    ]


def receiver_ecef(record: Record) -> tuple[float, float, float]:
    """Observer ECEF from a BESTPOS or BESTXYZ record."""
    if "p_x" in record:
        return record.real("p_x"), record.real("p_y"), record.real("p_z")
    height = record.real("hgt") + record.real("undulation")
    return ecef_from_geodetic(record.real("lat"), record.real("lon"), height)


def records_from(record: Record, key: str) -> tuple[Record, ...]:
    """Return a nested record sequence, tolerating a missing key."""
    try:
        return record.records(key)
    except (KeyError, TypeError):
        return ()
