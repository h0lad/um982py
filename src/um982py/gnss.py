"""GNSS reference constants and time-scale conversions.

Every physical, ICD and time-scale constant used by the library is defined
here once, together with the GPST, BDT and UTC conversions that need no
receiver message. The module imports nothing from the package.
"""

import math
from datetime import UTC, datetime, timedelta

__all__ = [
    "BDT_EPOCH",
    "BDT_GPS_SECONDS",
    "BDT_GPS_WEEKS",
    "DAY_SECONDS",
    "EARTH_ROTATION_RATE",
    "EARTH_ROTATION_RATE_BEIDOU",
    "EARTH_ROTATION_RATE_GLONASS",
    "F_B1I",
    "F_B3I",
    "F_E5B",
    "F_E6",
    "F_G1",
    "F_G1_STEP",
    "F_G2",
    "F_G2_STEP",
    "F_G3",
    "F_L1",
    "F_L2",
    "F_L5",
    "GPS_EPOCH",
    "IONOSPHERE_CONSTANT",
    "J2_GLONASS",
    "MU",
    "MU_GALILEO_BEIDOU",
    "MU_GLONASS",
    "PZ90_A",
    "SPEED_OF_LIGHT",
    "TECU",
    "WEEK_SECONDS",
    "WGS84_A",
    "WGS84_E2",
    "WGS84_F",
    "b2b_epoch",
    "bdt_week_to_gps_seconds",
    "gps_to_utc",
    "has_epoch",
    "leap_seconds_at",
    "unwrap_time",
    "wrap",
]

SPEED_OF_LIGHT = 299_792_458.0
"""Speed of light in vacuum (m/s)."""

WGS84_A = 6_378_137.0
"""WGS84 semi-major axis (m)."""
WGS84_F = 1 / 298.257_223_563
"""WGS84 flattening."""
WGS84_E2 = WGS84_F * (2 - WGS84_F)
"""WGS84 first eccentricity squared."""

MU = 3.986005e14
"""GPS/QZSS geocentric gravitational constant, IS-GPS-200 (m^3/s^2)."""
MU_GALILEO_BEIDOU = 3.986004418e14
"""Galileo OS SIS ICD and BeiDou B1I ICD gravitational constant (m^3/s^2)."""
MU_GLONASS = 3.9860044e14
"""GLONASS PZ-90 ICD gravitational constant (m^3/s^2)."""
EARTH_ROTATION_RATE = 7.2921151467e-5
"""GPS/Galileo Earth rotation rate (rad/s), IS-GPS-200 and Galileo OS SIS ICD."""
EARTH_ROTATION_RATE_BEIDOU = EARTH_ROTATION_RATE_GLONASS = 7.292115e-5
"""BeiDou B1I ICD and GLONASS PZ-90 ICD Earth rotation rate (rad/s)."""
PZ90_A = 6_378_136.0
"""PZ-90 semi-major axis used by the GLONASS equations of motion (m)."""
J2_GLONASS = 1.0826257e-3
"""Second zonal harmonic of the GLONASS ICD geopotential."""

IONOSPHERE_CONSTANT = 40.3
"""First-order ionospheric delay constant, delay = 40.3 TEC / f^2 (m^3/s^2)."""
TECU = 1e16
"""One TEC unit in electrons per square metre."""

F_L1 = 1575.42e6
"""GPS L1, Galileo E1, BeiDou B1C, QZSS L1 and SBAS L1 carrier (Hz)."""
F_L2 = 1227.60e6
"""GPS and QZSS L2 carrier (Hz)."""
F_L5 = 1176.45e6
"""GPS L5, Galileo E5a, BeiDou B2a, QZSS L5 and NavIC L5 carrier (Hz)."""
F_E5B = 1207.14e6
"""Galileo E5b and BeiDou B2I/B2b carrier (Hz)."""
F_E6 = 1278.75e6
"""Galileo E6 and QZSS L6 carrier (Hz)."""
F_B1I = 1561.098e6
"""BeiDou B1I carrier (Hz)."""
F_B3I = 1268.52e6
"""BeiDou B3I carrier (Hz)."""
F_G1, F_G1_STEP = 1602.0e6, 0.5625e6
"""GLONASS G1 FDMA centre and channel spacing (Hz)."""
F_G2, F_G2_STEP = 1246.0e6, 0.4375e6
"""GLONASS G2 FDMA centre and channel spacing (Hz)."""
F_G3 = 1202.025e6
"""GLONASS G3 CDMA carrier (Hz)."""

WEEK_SECONDS = 604_800
DAY_SECONDS = 86_400
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
"""Start of GPS week zero."""
BDT_GPS_WEEKS = 1356
"""GPS week in which BDT week zero starts."""
BDT_GPS_SECONDS = 14.0
"""Nominal GPST minus BDT offset (s)."""
BDT_EPOCH = GPS_EPOCH + timedelta(weeks=BDT_GPS_WEEKS)
"""Start of BDT week zero on the BDT calendar."""


def wrap(value: float, period: float) -> float:
    """Wrap a time difference into [-period / 2, period / 2)."""
    return (value + period / 2) % period - period / 2


def unwrap_time(reference: float, time_of_period: float, period: float) -> float:
    """Resolve a time of week or day to the absolute time nearest ``reference``."""
    base = reference - reference % period
    candidate = base + time_of_period
    difference = candidate - reference
    if difference > period / 2:
        return candidate - period
    if difference < -period / 2:
        return candidate + period
    return candidate


def _check_week_time(week: int, seconds_of_week: float, scale: str) -> None:
    if type(week) is not int or not 0 <= week <= 65535:
        raise ValueError(f"{scale} week must be an integer in 0..65535")
    if (
        isinstance(seconds_of_week, bool)
        or not math.isfinite(seconds_of_week)
        or not 0 <= seconds_of_week < WEEK_SECONDS
    ):
        raise ValueError(f"{scale} seconds outside week range")


def bdt_week_to_gps_seconds(week: int, seconds_of_week: float) -> float:
    """Convert a continuous BDT week and seconds to nominal GPST seconds.

    BDT week zero starts in GPS week 1356, and BDT is nominally 14 seconds
    behind GPST. The conversion uses this nominal offset.
    """
    _check_week_time(week, seconds_of_week, "BDT")
    return (
        (week + BDT_GPS_WEEKS) * float(WEEK_SECONDS)
        + seconds_of_week
        + (BDT_GPS_SECONDS)
    )


def _check_leap_seconds(leap_seconds: int) -> None:
    if type(leap_seconds) is not int or not 0 <= leap_seconds <= 99:
        raise ValueError("GPS-UTC leap seconds must be an integer in 0..99")


def gps_to_utc(week: int, seconds_of_week: float, *, leap_seconds: int) -> datetime:
    """Convert GPS week and seconds to UTC using a verified GPS-UTC offset.

    Python datetimes cannot represent a leap second. The caller supplies the
    offset valid at the observation epoch.
    """
    _check_week_time(week, seconds_of_week, "GPS")
    _check_leap_seconds(leap_seconds)
    return GPS_EPOCH + timedelta(weeks=week, seconds=seconds_of_week - leap_seconds)


def b2b_epoch(received_gps_seconds: float, seconds_of_day: int) -> float:
    """Resolve a BeiDou seconds-of-day tag to the nearest GPS day, adding 14 s."""
    if not math.isfinite(received_gps_seconds):
        raise ValueError("receiver epoch must be finite")
    if type(seconds_of_day) is not int or not 0 <= seconds_of_day < DAY_SECONDS:
        raise ValueError("BeiDou seconds of day must be in 0..86399")
    received_bdt = received_gps_seconds - BDT_GPS_SECONDS
    return unwrap_time(received_bdt, seconds_of_day, DAY_SECONDS) + BDT_GPS_SECONDS


def has_epoch(received_gps_seconds: float, time_of_hour: int) -> float:
    """Resolve a Galileo HAS time of hour to the latest hour not after receipt.

    GST counts the same seconds as GPST, so the result is in GPS seconds.
    """
    if not math.isfinite(received_gps_seconds):
        raise ValueError("receiver epoch must be finite")
    if type(time_of_hour) is not int or not 0 <= time_of_hour < 3600:
        raise ValueError("HAS time of hour must be in 0..3599")
    epoch = math.floor(received_gps_seconds / 3600) * 3600 + time_of_hour
    return epoch - 3600 if epoch > received_gps_seconds else epoch


def leap_seconds_at(
    gps_seconds: float, *, deltat_ls: int, wn_lsf: int, dn: int, deltat_lsf: int
) -> int:
    """GPS-UTC whole seconds at an epoch from broadcast UTC parameters.

    IS-GPS-200 section 20.3.3.5.2.4: ``deltat_lsf`` takes effect at the end
    of day ``dn`` (1 = Sunday) of week ``wn_lsf``, at UTC midnight. An 8-bit
    ``wn_lsf`` is resolved to the week nearest the epoch.
    """
    if not math.isfinite(gps_seconds):
        raise ValueError("GPS epoch must be finite")
    _check_leap_seconds(deltat_ls)
    _check_leap_seconds(deltat_lsf)
    if type(dn) is not int or not 1 <= dn <= 7:
        raise ValueError("leap-second day number must be in 1..7")
    if type(wn_lsf) is not int or wn_lsf < 0:
        raise ValueError("leap-second week must be a non-negative integer")
    week = gps_seconds / WEEK_SECONDS
    if wn_lsf < 256:
        wn_lsf = round(unwrap_time(week, wn_lsf, 256))
    effective = wn_lsf * WEEK_SECONDS + dn * DAY_SECONDS + deltat_ls
    return deltat_lsf if gps_seconds >= effective else deltat_ls
