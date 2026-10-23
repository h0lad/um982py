"""Antenna and authorization CONFIG commands."""

from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, text
from um982py.messages import CommandResponse


def antenna_delta(
    height: float, east: float = 0, north: float = 0
) -> Command[CommandResponse]:
    return config(
        "ANTENNADELTAHEN",
        number(height, 0, 6.5535),
        number(east, 0, 100),
        number(north, 0, 100),
    )


def base_antenna_model(
    name: str = "ADVNULLANTENNA",
    serial_number: str = "a0001",
    setup_id: int = 0,
    kind: Literal["NO", "USER"] = "NO",
) -> Command[CommandResponse]:
    return config(
        "BASEANTENNAMODEL",
        text(name, 31, quoted=True),
        text(serial_number, 31),
        integer(setup_id, 0, 255),
        option(kind, ("NO", "USER")),
    )


def authorization(code: str) -> Command[CommandResponse]:
    return config("AUTHCODE", text(code, 4096))
