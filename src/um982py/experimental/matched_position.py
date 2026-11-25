"""MATCHEDPOS rover positions paired with matched solutions."""

import math
from dataclasses import dataclass, replace

from um982py.antenna import antenna_index
from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.geodesy import enu_angles, enu_between, receiver_ecef
from um982py.messages import AsciiMessage, BinaryMessage, CommandResponse, Message
from um982py.messages.layouts.firmware import LAYOUTS
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record

__all__ = [
    "MatchedBaseline",
    "decode_matched_position",
    "matched_baseline",
    "matched_position_output",
    "matched_position_read",
    "matched_position_stop",
]

_LAYOUT = LAYOUTS["BESTPOS"]
_MESSAGE_ID = 96
# MATCHEDPOSH is the secondary-antenna rover of the heading engine.
_LOGS = {1: ("MATCHEDPOS", _MESSAGE_ID), 2: ("MATCHEDPOSH", 6006)}
_NAMES = {message_id: name for name, message_id in _LOGS.values()}


def decode_matched_position(message: Message) -> Record:
    """Decode a MATCHEDPOS or MATCHEDPOSH frame with the BESTPOS layout."""
    if isinstance(message, BinaryMessage):
        name = _NAMES.get(message.header.message_id)
        if name is None:
            raise ProtocolError(
                "Expected MATCHEDPOSB message ID 96 or MATCHEDPOSHB message ID 6006"
            )
        values: bytes | tuple[str, ...] = message.payload
    elif isinstance(message, AsciiMessage) and message.name in (
        "MATCHEDPOSA",
        "MATCHEDPOSHA",
    ):
        name = message.name[:-1]
        values = message.fields
    else:
        raise ProtocolError("Expected a MATCHEDPOS frame")
    record = BodyReader(values).read(_LAYOUT)
    return replace(record, name=name, message=message)


def matched_position_read(
    *, antenna: int | str = 1, port: Port | None = None
) -> Command[Record]:
    """Request one binary matched position for the selected antenna."""
    name, message_id = _LOGS[antenna_index(antenna)]
    return logging.request(name + "B", port=port, message_id=message_id).decoded_with(
        decode_matched_position
    )


def matched_position_output(
    *, antenna: int | str = 1, port: Port | None = None
) -> Command[CommandResponse]:
    name, _ = _LOGS[antenna_index(antenna)]
    return logging.output(name + "B", Trigger.ON_CHANGED, port=port)


def matched_position_stop(
    *, antenna: int | str = 1, port: Port | None = None
) -> Command[CommandResponse]:
    name, _ = _LOGS[antenna_index(antenna)]
    return logging.stop(name + "B", port=port)


@dataclass(frozen=True, slots=True)
class MatchedBaseline:
    """Heading-engine baseline from its base position to the matched rover.

    The vector reproduces UNIHEADING length, heading and pitch, and also gives
    the full ECEF components.
    """

    ecef_m: tuple[float, float, float]
    enu_m: tuple[float, float, float]
    length_m: float
    heading_deg: float
    pitch_deg: float


def matched_baseline(base: Record, rover: Record) -> MatchedBaseline:
    """Baseline from a BASESTATION reference to a MATCHEDPOSH position.

    Both records should share an epoch. The local frame is the base position.
    """
    if base.name != "BASESTATION" or rover.name != "MATCHEDPOSH":
        raise ValueError("expected BASESTATION and MATCHEDPOSH records")
    origin = receiver_ecef(base)
    target = receiver_ecef(rover)
    enu = enu_between(origin, target)
    heading, pitch = enu_angles(*enu)
    return MatchedBaseline(
        ecef_m=(target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]),
        enu_m=enu,
        length_m=math.hypot(*enu),
        heading_deg=heading,
        pitch_deg=pitch,
    )
