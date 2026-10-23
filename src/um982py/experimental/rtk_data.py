"""RTKDATA engine covariance and per-satellite states."""

import math
from dataclasses import dataclass
from struct import Struct, unpack_from

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import BinaryMessage, CommandResponse, Message
from um982py.messages.enums import MessageSatelliteSystem

__all__ = [
    "RtkData",
    "RtkDataSatellite",
    "decode_rtk_data",
    "rtk_data2_output",
    "rtk_data2_read",
    "rtk_data2_stop",
    "rtk_data_output",
    "rtk_data_read",
    "rtk_data_stop",
]

_IDS = {215: "RTKDATA", 2027: "RTKDATA2"}
_ENTRY = Struct("<III")
_HEADER_SIZE = 108
_MATRIX_OFFSET = 28
_MATRIX_COUNT = 9
_MAX_ENTRIES = 64
_SYSTEM_OFFSETS = (
    (MessageSatelliteSystem.GPS, 1, 32, 0),
    (MessageSatelliteSystem.GALILEO, 75, 110, 74),
    (MessageSatelliteSystem.BEIDOU, 161, 205, 160),
)


@dataclass(frozen=True, slots=True)
class RtkDataSatellite:
    """One engine entry with resolved identity and neutral state fields."""

    satellite_id: int
    system: MessageSatelliteSystem | None
    prn: int | None
    status: int
    value: int


@dataclass(frozen=True, slots=True)
class RtkData:
    """One RTKDATA frame with covariance and per-satellite states."""

    message: BinaryMessage
    name: str
    header_fields_raw: bytes
    covariance: tuple[float, ...]
    satellites: tuple[RtkDataSatellite, ...]


def _identity(satellite_id: int) -> tuple[MessageSatelliteSystem | None, int | None]:
    """Resolve the system and PRN, leaving unmapped identifiers unresolved."""
    for system, first, last, offset in _SYSTEM_OFFSETS:
        if first <= satellite_id <= last:
            return system, satellite_id - offset
    return None, None


def decode_rtk_data(message: Message) -> RtkData:
    """Decode an RTKDATA frame without assigning state semantics."""
    if not isinstance(message, BinaryMessage) or message.header.message_id not in _IDS:
        raise ProtocolError("Expected RTKDATA message ID 215 or RTKDATA2 ID 2027")
    payload = message.payload
    if len(payload) < _HEADER_SIZE or (len(payload) - _HEADER_SIZE) % _ENTRY.size:
        raise ProtocolError("Invalid RTKDATA body length")
    count = (len(payload) - _HEADER_SIZE) // _ENTRY.size
    if count > _MAX_ENTRIES:
        raise ProtocolError("Invalid RTKDATA entry count")
    covariance = tuple(
        unpack_from("<f", payload, _MATRIX_OFFSET + 4 * index)[0]
        for index in range(_MATRIX_COUNT)
    )
    if not all(math.isfinite(value) for value in covariance):
        raise ProtocolError("Non-finite RTKDATA covariance value")
    satellites = []
    for index in range(count):
        satellite_id, status, value = _ENTRY.unpack_from(
            payload, _HEADER_SIZE + index * _ENTRY.size
        )
        system, prn = _identity(satellite_id)
        satellites.append(RtkDataSatellite(satellite_id, system, prn, status, value))
    return RtkData(
        message,
        _IDS[message.header.message_id],
        payload[:_HEADER_SIZE],
        covariance,
        tuple(satellites),
    )


def _read(name: str, message_id: int, port: Port | None) -> Command[RtkData]:
    """Request one binary RTKDATA frame."""
    request = logging.request(name, port=port, message_id=message_id)
    return Command(request.text, request.matches, decode_rtk_data)


def _output(name: str, port: Port | None) -> Command[CommandResponse]:
    """Subscribe to changes in a binary RTKDATA report."""
    return logging.output(name, Trigger.ON_CHANGED, port=port)


def _stop(name: str, port: Port | None) -> Command[CommandResponse]:
    """Stop a previously started RTKDATA subscription."""
    return logging.stop(name, port=port)


def rtk_data_read(*, port: Port | None = None) -> Command[RtkData]:
    """Request one binary RTKDATA frame."""
    return _read("RTKDATAB", 215, port)


def rtk_data_output(*, port: Port | None = None) -> Command[CommandResponse]:
    """Subscribe to changes in the binary RTKDATA report."""
    return _output("RTKDATAB", port)


def rtk_data_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a previously started RTKDATA subscription."""
    return _stop("RTKDATAB", port)


def rtk_data2_read(*, port: Port | None = None) -> Command[RtkData]:
    """Request one binary RTKDATA2 frame."""
    return _read("RTKDATA2B", 2027, port)


def rtk_data2_output(*, port: Port | None = None) -> Command[CommandResponse]:
    """Subscribe to changes in the binary RTKDATA2 report."""
    return _output("RTKDATA2B", port)


def rtk_data2_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a previously started RTKDATA2 subscription."""
    return _stop("RTKDATA2B", port)
