"""Native Doppler velocity from the firmware VELDATA log."""

import math
from dataclasses import dataclass
from struct import Struct, unpack_from

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port
from um982py.errors import ProtocolError
from um982py.messages import BinaryMessage, CommandResponse, Message

__all__ = [
    "VelocityData",
    "decode_velocity_data",
    "velocity_data_output",
    "velocity_data_read",
    "velocity_data_stop",
]

_MESSAGE_ID = 95
_LOG_NAME = "VELDATAB"
_BODY_SIZE = 120
_VELOCITY = Struct("<3d")


@dataclass(frozen=True, slots=True)
class VelocityData:
    """Native ECEF Doppler velocity and square root of total velocity variance."""

    message: BinaryMessage
    gps_week: int
    milliseconds_of_week: int
    velocity_ecef_mps: tuple[float, float, float]
    uncertainty_3d_mps: float

    @property
    def epoch_gps_seconds(self) -> float:
        """Return GPS seconds from the velocity epoch in the payload."""
        return self.gps_week * 604800 + self.milliseconds_of_week / 1000


def decode_velocity_data(message: Message) -> VelocityData:
    """Decode the fields verified on the UM982 R4.10Build25164."""
    if (
        not isinstance(message, BinaryMessage)
        or message.header.message_id != _MESSAGE_ID
    ):
        raise ProtocolError("Expected VELDATAB message ID 95")
    payload = message.payload
    if len(payload) != _BODY_SIZE:
        raise ProtocolError("Invalid VELDATAB body length")
    week, milliseconds = unpack_from("<H2xI", payload)
    if milliseconds >= 604800000:
        raise ProtocolError("Invalid VELDATAB GPS milliseconds of week")
    vx, vy, vz = _VELOCITY.unpack_from(payload, 16)
    deviations = _VELOCITY.unpack_from(payload, 48)
    if not all(math.isfinite(value) for value in (vx, vy, vz)):
        raise ProtocolError("Non-finite VELDATAB velocity")
    uncertainty = math.hypot(*deviations)
    if not math.isfinite(uncertainty) or any(value < 0 for value in deviations):
        raise ProtocolError("Invalid VELDATAB velocity uncertainty")
    return VelocityData(message, week, milliseconds, (vx, vy, vz), uncertainty)


def velocity_data_read(*, port: Port | None = None) -> Command[VelocityData]:
    """Request one binary VELDATA report."""
    request = logging.request(_LOG_NAME, port=port, message_id=_MESSAGE_ID)
    return Command(request.text, request.matches, decode_velocity_data)


def velocity_data_output(
    interval: float | None = None,
    *,
    rate_hz: float | None = None,
    port: Port | None = None,
) -> Command[CommandResponse]:
    """Subscribe to periodic binary VELDATA reports."""
    return logging.output(
        _LOG_NAME, logging.output_interval(interval, rate_hz), port=port
    )


def velocity_data_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop the binary VELDATA subscription."""
    return logging.stop(_LOG_NAME, port=port)
