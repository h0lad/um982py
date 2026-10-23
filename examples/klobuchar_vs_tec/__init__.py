"""Compares Klobuchar delay with dual-frequency vertical TEC."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from examples.ionosphere_tec import Observation, slant_tec
from um982py.geodesy import SPEED_OF_LIGHT
from um982py.messages import Record

GPS_L1_HZ = 1575.42e6
IONOSPHERE_COEFFICIENT = 40.3
TECU = 1e16
NIGHT_TIME_DELAY_SECONDS = 5e-9
SECONDS_PER_DAY = 86_400.0
PEAK_LOCAL_SECONDS = 50_400.0
SEMICIRCLE_DEGREES = 180.0
GEOMAGNETIC_LIMIT = 0.416

__all__ = [
    "GPS_L1_HZ",
    "IONOSPHERE_COEFFICIENT",
    "NIGHT_TIME_DELAY_SECONDS",
    "KlobucharCoefficients",
    "diurnal_profile",
    "geomagnetic_coordinates",
    "local_solar_seconds",
    "measured_vertical_delay",
    "obliquity_factor",
    "vertical_delay_from_slant_tec",
    "vertical_delay_metres",
    "vertical_delay_seconds",
]


@dataclass(frozen=True, slots=True)
class KlobucharCoefficients:
    """GPS broadcast ionosphere coefficients ``a0..a3`` and ``b0..b3``."""

    a0: float
    a1: float
    a2: float
    a3: float
    b0: float
    b1: float
    b2: float
    b3: float

    @classmethod
    def from_record(cls, record: Record) -> KlobucharCoefficients:
        """Build the coefficient set from a decoded GPSION record."""
        return cls(
            a0=record.real("a0"),
            a1=record.real("a1"),
            a2=record.real("a2"),
            a3=record.real("a3"),
            b0=record.real("b0"),
            b1=record.real("b1"),
            b2=record.real("b2"),
            b3=record.real("b3"),
        )

    def amplitude(self, geomagnetic_latitude: float) -> float:
        """Amplitude term in seconds, clamped to the non-negative range."""
        value = (
            self.a0
            + self.a1 * geomagnetic_latitude
            + self.a2 * geomagnetic_latitude**2
            + self.a3 * geomagnetic_latitude**3
        )
        return max(value, 0.0)

    def period(self, geomagnetic_latitude: float) -> float:
        """Period term in seconds, clamped to the 72 000 s lower bound."""
        value = (
            self.b0
            + self.b1 * geomagnetic_latitude
            + self.b2 * geomagnetic_latitude**2
            + self.b3 * geomagnetic_latitude**3
        )
        return max(value, 72_000.0)


def obliquity_factor(elevation_degrees: float) -> float:
    """Klobuchar slant-to-vertical mapping factor at an elevation in degrees."""
    if not 0.0 <= elevation_degrees <= 90.0:
        raise ValueError("elevation must be in 0..90 degrees")
    elevation = elevation_degrees / SEMICIRCLE_DEGREES
    return 1.0 + 16.0 * (0.53 - elevation) ** 3


def geomagnetic_coordinates(
    latitude_degrees: float,
    longitude_degrees: float,
    elevation_degrees: float,
    azimuth_degrees: float,
) -> tuple[float, float]:
    """Geomagnetic latitude and local longitude in semicircles."""
    elevation = elevation_degrees / SEMICIRCLE_DEGREES
    azimuth = math.radians(azimuth_degrees)
    latitude = latitude_degrees / SEMICIRCLE_DEGREES
    longitude = longitude_degrees / SEMICIRCLE_DEGREES
    angular_offset = 0.0137 / (elevation + 0.11) - 0.022
    geomagnetic_latitude = latitude + angular_offset * math.cos(azimuth)
    geomagnetic_latitude = max(
        -GEOMAGNETIC_LIMIT, min(GEOMAGNETIC_LIMIT, geomagnetic_latitude)
    )
    geomagnetic_longitude = longitude + (
        angular_offset * math.sin(azimuth) / math.cos(geomagnetic_latitude * math.pi)
    )
    return geomagnetic_latitude, geomagnetic_longitude


def vertical_delay_seconds(
    coefficients: KlobucharCoefficients,
    *,
    latitude: float,
    longitude: float,
    elevation: float,
    azimuth: float,
    gps_seconds: float,
) -> float:
    """Klobuchar vertical ionospheric delay in seconds at L1."""
    geomagnetic_latitude, geomagnetic_longitude = geomagnetic_coordinates(
        latitude, longitude, elevation, azimuth
    )
    magnetic_latitude = geomagnetic_latitude + 0.064 * math.cos(
        geomagnetic_longitude - 1.617
    )
    local_seconds = (43_200.0 * geomagnetic_longitude + gps_seconds) % SECONDS_PER_DAY
    period = coefficients.period(magnetic_latitude)
    amplitude = coefficients.amplitude(magnetic_latitude)
    phase = 2.0 * math.pi * (local_seconds - PEAK_LOCAL_SECONDS) / period
    factor = obliquity_factor(elevation)
    if abs(phase) < 1.57:
        slant = factor * (
            NIGHT_TIME_DELAY_SECONDS
            + amplitude * (1.0 - phase**2 / 2.0 + phase**4 / 24.0)
        )
    else:
        slant = factor * NIGHT_TIME_DELAY_SECONDS
    return slant / factor


def vertical_delay_metres(
    coefficients: KlobucharCoefficients,
    *,
    latitude: float,
    longitude: float,
    elevation: float,
    azimuth: float,
    gps_seconds: float,
) -> float:
    """Klobuchar vertical ionospheric delay in metres at L1."""
    return SPEED_OF_LIGHT * vertical_delay_seconds(
        coefficients,
        latitude=latitude,
        longitude=longitude,
        elevation=elevation,
        azimuth=azimuth,
        gps_seconds=gps_seconds,
    )


def vertical_delay_from_slant_tec(
    slant_tec_tecu: float, elevation_degrees: float
) -> float:
    """L1 vertical delay in metres from a slant TEC in TECU."""
    vertical_tec = slant_tec_tecu / obliquity_factor(elevation_degrees)
    return IONOSPHERE_COEFFICIENT * vertical_tec * TECU / GPS_L1_HZ**2


def measured_vertical_delay(
    observations: Sequence[Observation], elevation_degrees: float
) -> float | None:
    """Vertical L1 delay in metres from a dual-frequency observation pair."""
    tec = slant_tec(observations)
    if tec is None:
        return None
    return vertical_delay_from_slant_tec(tec, elevation_degrees)


def local_solar_seconds(gps_seconds: float, longitude_degrees: float) -> float:
    """Local solar time of day in seconds for a longitude."""
    offset = longitude_degrees / 15.0 * 3600.0
    return (gps_seconds + offset) % SECONDS_PER_DAY


def diurnal_profile(
    coefficients: KlobucharCoefficients,
    *,
    latitude: float,
    longitude: float,
    elevation: float,
    azimuth: float,
    start_seconds: float,
    hours: float = 24.0,
    step_seconds: float = 300.0,
) -> tuple[tuple[float, float], ...]:
    """Local solar seconds and vertical delay in metres over a time span."""
    if hours <= 0:
        raise ValueError("hours must be positive")
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    samples = int(hours * 3600.0 / step_seconds) + 1
    return tuple(
        (
            local_solar_seconds(start_seconds + index * step_seconds, longitude),
            vertical_delay_metres(
                coefficients,
                latitude=latitude,
                longitude=longitude,
                elevation=elevation,
                azimuth=azimuth,
                gps_seconds=start_seconds + index * step_seconds,
            ),
        )
        for index in range(samples)
    )
