"""Assisted position and time commands."""

from datetime import UTC, datetime

from um982py.commands.core import Command, action, number
from um982py.commands.validation import integer
from um982py.messages import CommandResponse


def _coordinate(value: float, limit: int, width: int) -> str:
    number(value, -limit, limit)
    total = round(abs(value) * 60, 6)
    degrees = int(total // 60)
    minutes = total - degrees * 60
    return f"{degrees:0{width}d}{minutes:09.6f}"


def position(
    latitude: float, longitude: float, altitude: float
) -> Command[CommandResponse]:
    lat = _coordinate(latitude, 90, 2)
    lon = _coordinate(longitude, 180, 3)
    height = number(altitude, -float("inf"), float("inf"))
    latitude_direction = "S" if latitude < 0 else "N"
    longitude_direction = "W" if longitude < 0 else "E"
    return action(
        f"AIDPOS,{lat},{latitude_direction},{lon},{longitude_direction},{height}",
        dollar_prefixed=True,
    )


def time_fields(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    millisecond: int,
    leap_seconds: int = 18,
) -> Command[CommandResponse]:
    integer(year, 1, 9999)
    integer(month, 1, 12)
    integer(day, 1, 31)
    integer(hour, 0, 23)
    integer(minute, 0, 59)
    integer(second, 0, 60)
    datetime(year, month, day, hour, minute, min(second, 59), tzinfo=UTC)
    values = (
        year,
        month,
        day,
        hour,
        minute,
        second,
        int(integer(millisecond, 0, 999)),
        int(integer(leap_seconds, 0, 255)),
    )
    return action("AIDTIME," + ",".join(map(str, values)), dollar_prefixed=True)


def time(moment: datetime, *, leap_seconds: int = 18) -> Command[CommandResponse]:
    if moment.utcoffset() is None:
        raise ValueError("Assisted time requires a timezone-aware datetime")
    moment = moment.astimezone(UTC)
    return time_fields(
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
        leap_seconds,
    )
