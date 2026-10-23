"""Converts GPST to UTC through the leap-second table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

__all__ = [
    "LEAP_SECONDS",
    "LeapSecond",
    "date_of_year",
    "day_of_year",
    "gpst_from_utc",
    "leap_seconds",
    "utc_from_gpst",
    "utc_offset_seconds",
]


@dataclass(frozen=True, slots=True)
class LeapSecond:
    """One leap-second step of ``total_seconds`` in force from ``effective``."""

    effective: datetime
    total_seconds: int


LEAP_SECONDS: tuple[LeapSecond, ...] = (
    LeapSecond(datetime(2017, 1, 1), 18),
    LeapSecond(datetime(2015, 7, 1), 17),
    LeapSecond(datetime(2012, 7, 1), 16),
    LeapSecond(datetime(2009, 1, 1), 15),
    LeapSecond(datetime(2006, 1, 1), 14),
    LeapSecond(datetime(1999, 1, 1), 13),
    LeapSecond(datetime(1997, 7, 1), 12),
    LeapSecond(datetime(1996, 1, 1), 11),
    LeapSecond(datetime(1994, 7, 1), 10),
    LeapSecond(datetime(1993, 7, 1), 9),
    LeapSecond(datetime(1992, 7, 1), 8),
    LeapSecond(datetime(1991, 1, 1), 7),
    LeapSecond(datetime(1990, 1, 1), 6),
    LeapSecond(datetime(1988, 1, 1), 5),
    LeapSecond(datetime(1985, 7, 1), 4),
    LeapSecond(datetime(1983, 7, 1), 3),
    LeapSecond(datetime(1982, 7, 1), 2),
    LeapSecond(datetime(1981, 7, 1), 1),
    LeapSecond(datetime(1980, 1, 6), 0),
)


def leap_seconds(utc: datetime) -> int:
    """GPST minus UTC in whole seconds at a UTC epoch."""
    for entry in LEAP_SECONDS:
        if utc >= entry.effective:
            return entry.total_seconds
    raise ValueError("epoch predates the tabulated leap seconds")


def gpst_from_utc(utc: datetime) -> datetime:
    """Advance a UTC epoch by the leap seconds in force."""
    return utc + timedelta(seconds=leap_seconds(utc))


def utc_from_gpst(gpst: datetime) -> datetime:
    """Retreat a GPST epoch by the leap seconds in force."""
    for entry in LEAP_SECONDS:
        utc = gpst - timedelta(seconds=entry.total_seconds)
        if utc >= entry.effective:
            return utc
    raise ValueError("epoch predates the tabulated leap seconds")


def utc_offset_seconds(gpst: datetime) -> float:
    """The ``TIME.utc_offset`` convention: UTC minus GPST in seconds."""
    return float(-leap_seconds(utc_from_gpst(gpst)))


def day_of_year(moment: date) -> int:
    """Day number within the year, 1 for January 1."""
    return moment.toordinal() - date(moment.year, 1, 1).toordinal() + 1


def date_of_year(year: int, day: int) -> date:
    """Calendar date of a day number within ``year``."""
    if day < 1:
        raise ValueError("day must be positive")
    result = date(year, 1, 1) + timedelta(days=day - 1)
    if result.year != year:
        raise ValueError("day is outside the year")
    return result
