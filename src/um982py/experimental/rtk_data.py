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
    "rtk_datah_output",
    "rtk_datah_read",
    "rtk_datah_stop",
]

_HEADING_ID = 6007
_IDS = {215: "RTKDATA", 2027: "RTKDATA2", _HEADING_ID: "RTKDATAH"}
_ENTRY = Struct("<III")
_HEADER_SIZE = 108
# Labels from the R4.10Build25164 RTKDATAHA formatter's ambiguity table.
_HEADING_STATUS_LABELS = {
    0: "UNDEFINED",
    1: "L5_FLOAT",
    2: "L4_FLOAT",
    3: "L3_FLOAT",
    4: "L2_FLOAT",
    5: "L1_FLOAT",
    6: "NARROW_FLOAT_L45",
    7: "NARROW_FLOAT_L35",
    8: "NARROW_FLOAT_L25",
    9: "NARROW_FLOAT_L15",
    10: "NARROW_FLOAT_L34",
    11: "NARROW_FLOAT_L24",
    12: "NARROW_FLOAT_L14",
    13: "NARROW_FLOAT_L23",
    14: "NARROW_FLOAT_L13",
    15: "NARROW_FLOAT",
    16: "NARROW_FLOAT_L345",
    17: "NARROW_FLOAT_L245",
    18: "NARROW_FLOAT_L145",
    19: "NARROW_FLOAT_L235",
    20: "NARROW_FLOAT_L135",
    21: "NARROW_FLOAT_L125",
    22: "NARROW_FLOAT_L234",
    23: "NARROW_FLOAT_L134",
    24: "NARROW_FLOAT_L124",
    25: "NARROW_FLOAT_L123",
    26: "NARROW_FLOAT_L2345",
    27: "NARROW_FLOAT_L1345",
    28: "NARROW_FLOAT_L1245",
    29: "NARROW_FLOAT_L1235",
    30: "NARROW_FLOAT_L1234",
    31: "NARROW_FLOAT_L12345",
    32: "WIDE_INT",
    33: "L5_INT",
    34: "L4_INT",
    35: "L3_INT",
    36: "L2_INT",
    37: "L1_INT",
    38: "NARROW_INT_L45",
    39: "NARROW_INT_L35",
    40: "NARROW_INT_L25",
    41: "NARROW_INT_L15",
    42: "NARROW_INT_L34",
    43: "NARROW_INT_L24",
    44: "NARROW_INT_L14",
    45: "NARROW_INT_L23",
    46: "NARROW_INT_L13",
    47: "NARROW_INT",
    48: "NARROW_INT_L345",
    49: "NARROW_INT_L245",
    50: "NARROW_INT_L145",
    51: "NARROW_INT_L235",
    52: "NARROW_INT_L135",
    53: "NARROW_INT_L125",
    54: "NARROW_INT_L234",
    55: "NARROW_INT_L134",
    56: "NARROW_INT_L124",
    57: "NARROW_INT_L123",
    58: "NARROW_INT_L2345",
    59: "NARROW_INT_L1345",
    60: "NARROW_INT_L1245",
    61: "NARROW_INT_L1235",
    62: "NARROW_INT_L1234",
    63: "NARROW_INT_L12345",
    70: "REFERENCE",
}
_SYSTEM_OFFSETS = (
    (MessageSatelliteSystem.GPS, 1, 32, 0),
    (MessageSatelliteSystem.GALILEO, 75, 110, 74),
    (MessageSatelliteSystem.BEIDOU, 161, 205, 160),
)


@dataclass(frozen=True, slots=True)
class RtkDataSatellite:
    """One engine entry with its satellite identity and raw state fields."""

    satellite_id: int
    system: MessageSatelliteSystem | None
    prn: int | None
    status: int
    value: int
    status_label: str | None = None

    @property
    def ambiguity_fixed(self) -> bool | None:
        """Indicate whether a classified heading ambiguity is integer-fixed."""
        if self.status_label is None or self.status in (0, 70):
            return None
        return 32 <= self.status <= 63


@dataclass(frozen=True, slots=True)
class RtkData:
    """Engine covariance in native row-major order and per-satellite states.

    Only RTKDATAH has verified solution codes and ambiguity labels. The
    covariance coordinate frame and per-satellite value units are unresolved.
    """

    message: BinaryMessage
    name: str
    header_fields_raw: bytes
    covariance: tuple[float, ...]
    satellites: tuple[RtkDataSatellite, ...]
    solution_status: int | None = None
    position_type: int | None = None


def _satellite_system_and_prn(
    satellite_id: int,
) -> tuple[MessageSatelliteSystem | None, int | None]:
    for system, first, last, offset in _SYSTEM_OFFSETS:
        if first <= satellite_id <= last:
            return system, satellite_id - offset
    return None, None


def decode_rtk_data(message: Message) -> RtkData:
    """Decode an RTKDATA frame into native fields."""
    if not isinstance(message, BinaryMessage) or message.header.message_id not in _IDS:
        raise ProtocolError("Expected RTKDATA message ID 215, 2027 or 6007")
    payload = message.payload
    is_heading = message.header.message_id == _HEADING_ID
    if len(payload) < _HEADER_SIZE or (len(payload) - _HEADER_SIZE) % _ENTRY.size:
        raise ProtocolError("Invalid RTKDATA body length")
    count = (len(payload) - _HEADER_SIZE) // _ENTRY.size
    if count > (80 if is_heading else 64):
        raise ProtocolError("Invalid RTKDATA entry count")
    if is_heading and unpack_from("<I", payload, 104)[0] != count:
        raise ProtocolError("RTKDATAH entry count does not match body length")
    covariance = unpack_from("<9f", payload, 28)
    if not all(math.isfinite(value) for value in covariance):
        raise ProtocolError("Non-finite RTKDATA covariance value")
    satellites = []
    for index in range(count):
        satellite_id, status, value = _ENTRY.unpack_from(
            payload, _HEADER_SIZE + index * _ENTRY.size
        )
        system, prn = _satellite_system_and_prn(satellite_id)
        label = _HEADING_STATUS_LABELS.get(status) if is_heading else None
        satellites.append(
            RtkDataSatellite(satellite_id, system, prn, status, value, label)
        )
    solution_status, position_type = (
        unpack_from("<2I", payload) if is_heading else (None, None)
    )
    return RtkData(
        message,
        _IDS[message.header.message_id],
        payload[:_HEADER_SIZE],
        covariance,
        tuple(satellites),
        solution_status,
        position_type,
    )


def _read(name: str, message_id: int, port: Port | None) -> Command[RtkData]:
    request = logging.request(name, port=port, message_id=message_id)
    return Command(request.text, request.matches, decode_rtk_data)


def _output(name: str, port: Port | None) -> Command[CommandResponse]:
    return logging.output(name, Trigger.ON_CHANGED, port=port)


def _stop(name: str, port: Port | None) -> Command[CommandResponse]:
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


def rtk_datah_read(*, port: Port | None = None) -> Command[RtkData]:
    """Request one binary heading-engine RTKDATAH frame."""
    return _read("RTKDATAHB", _HEADING_ID, port)


def rtk_datah_output(*, port: Port | None = None) -> Command[CommandResponse]:
    """Subscribe to heading-engine RTKDATAH changes."""
    return _output("RTKDATAHB", port)


def rtk_datah_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop the binary heading-engine RTKDATAH subscription."""
    return _stop("RTKDATAHB", port)
