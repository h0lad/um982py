"""MATCHEDSOLUTION binary framing and neutral fields."""

import math
from dataclasses import dataclass
from struct import Struct, unpack_from

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import BinaryMessage, CommandResponse, Message

_ENTRY = Struct("<HHIdIdId")
_HEADER_SIZE = 40
_MAX_ENTRIES = 80
_STATUS_LABELS = {0: "AMB_UNKNOWN", 4: "AMB_L2_FLOAT", 5: "AMB_L1_FLOAT"}


@dataclass(frozen=True, slots=True)
class MatchedSatellite:
    """One receiver entry with unverified status codes and value units."""

    satellite_id: int
    reserved: int
    status_codes: tuple[int, int, int]
    values: tuple[float, float, float]

    @property
    def status_labels(self) -> tuple[str | None, str | None, str | None]:
        """Return known receiver labels, leaving unrecognized codes unlabelled."""
        first, second, third = self.status_codes
        return (
            _STATUS_LABELS.get(first),
            _STATUS_LABELS.get(second),
            _STATUS_LABELS.get(third),
        )


@dataclass(frozen=True, slots=True)
class MatchedSolution:
    """A legacy receiver frame and its conservatively decoded entries."""

    message: BinaryMessage
    header_fields_raw: bytes
    satellites: tuple[MatchedSatellite, ...]


def decode_matched_solution(message: Message) -> MatchedSolution:
    """Decode observed binary framing without assigning units."""
    if not isinstance(message, BinaryMessage) or message.header.message_id != 2020:
        raise ProtocolError("Expected MATCHEDSOLUTIONB message ID 2020")
    payload = message.payload
    if len(payload) < _HEADER_SIZE:
        raise ProtocolError("Truncated MATCHEDSOLUTION header")
    count = unpack_from("<I", payload, 36)[0]
    if count > _MAX_ENTRIES or len(payload) != _HEADER_SIZE + count * _ENTRY.size:
        raise ProtocolError("Invalid MATCHEDSOLUTION entry count or body length")
    satellites = []
    for index in range(count):
        sat, reserved, s1, v1, s2, v2, s3, v3 = _ENTRY.unpack_from(
            payload, _HEADER_SIZE + index * _ENTRY.size
        )
        if not all(math.isfinite(value) for value in (v1, v2, v3)):
            raise ProtocolError("Non-finite MATCHEDSOLUTION value")
        satellites.append(MatchedSatellite(sat, reserved, (s1, s2, s3), (v1, v2, v3)))
    return MatchedSolution(message, payload[:36], tuple(satellites))


def matched_solution_read(*, port: Port | None = None) -> Command[MatchedSolution]:
    """Request one binary MATCHEDSOLUTION frame."""
    request = logging.request("MATCHEDSOLUTIONB", port=port, message_id=2020)
    return Command(request.text, request.matches, decode_matched_solution)


def matched_solution_output(*, port: Port | None = None) -> Command[CommandResponse]:
    """Subscribe to changes in the binary satellite status report."""
    return logging.output("MATCHEDSOLUTIONB", Trigger.ON_CHANGED, port=port)


def matched_solution_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a previously started binary satellite status subscription."""
    return logging.stop("MATCHEDSOLUTIONB", port=port)
