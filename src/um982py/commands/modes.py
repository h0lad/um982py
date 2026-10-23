"""Positioning and heading mode commands."""

from um982py.commands.configuration.heading import HeadingMode
from um982py.commands.core import Command, action, number
from um982py.commands.types import RoverDynamics
from um982py.commands.validation import integer, option
from um982py.messages.frames import CommandResponse


def rover_default() -> Command[CommandResponse]:
    """Select rover mode with the receiver's product-specific default profile."""
    return action("MODE ROVER")


def rover(
    dynamics: RoverDynamics = RoverDynamics.SURVEY,
    *,
    profile: str | None = None,
) -> Command[CommandResponse]:
    selected = RoverDynamics(dynamics).value
    if profile is None:
        return action(f"MODE ROVER {selected}")
    allowed = {
        "UAV": ("DEFAULT", "HIGHDYN"),
        "SURVEY": ("DEFAULT", "MOW"),
        "AUTOMOTIVE": ("DEFAULT",),
        "RACING": ("DEFAULT",),
    }
    return action(f"MODE ROVER {selected} {option(profile, allowed[selected])}")


def base_position(
    latitude: float,
    longitude: float,
    altitude: float,
    *,
    station_id: int | None = None,
) -> Command[CommandResponse]:
    parts = ["MODE BASE"]
    if station_id is not None:
        if type(station_id) is not int or not 0 <= station_id <= 4095:
            raise ValueError("station_id must be 0..4095")
        parts.append(str(station_id))
    parts.extend(
        (
            number(latitude, -90, 90),
            number(longitude, -180, 180),
            number(altitude, -30000, 30000),
        )
    )
    return action(" ".join(parts))


def heading(*, secondary: bool = False) -> Command[CommandResponse]:
    return action("MODE HEADING2" if secondary else "MODE HEADING")


def base(station_id: int | None = None) -> Command[CommandResponse]:
    return action(
        "MODE BASE"
        if station_id is None
        else f"MODE BASE {integer(station_id, 0, 4095)}"
    )


def base_survey(
    seconds: float = 60, *, distance: float | None = None, station_id: int | None = None
) -> Command[CommandResponse]:
    parts = [base(station_id).text, "TIME", number(seconds, 0, 3600)]
    if distance is not None:
        parts.append(number(distance, 0, 10))
    return action(" ".join(parts))


def base_ecef(
    x: float, y: float, z: float, *, station_id: int | None = None
) -> Command[CommandResponse]:
    if -90 <= x <= 90:
        raise ValueError(
            "The receiver interprets X within -90..90 as geodetic latitude"
        )
    coordinates = (number(value, -float("inf"), float("inf")) for value in (x, y, z))
    return action(" ".join((base(station_id).text, *coordinates)))


def heading2(mode: HeadingMode | None = None) -> Command[CommandResponse]:
    if mode is None:
        return action("MODE HEADING2")
    return action(
        "MODE HEADING2 "
        + option(
            mode, ("FIXLENGTH", "VARIABLELENGTH", "STATIC", "LOWDYNAMIC", "TRACTOR")
        )
    )
