"""MATCHEDPOS rover positions paired with matched solutions."""

from dataclasses import replace

from um982py._firmware_layouts import LAYOUTS
from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, CommandResponse, Message
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record

__all__ = [
    "decode_matched_position",
    "matched_position_output",
    "matched_position_read",
    "matched_position_stop",
]

_LAYOUT = LAYOUTS["BESTPOS"]
_MESSAGE_ID = 96


def decode_matched_position(message: Message) -> Record:
    """Decode a MATCHEDPOS frame with the BESTPOS position layout."""
    if isinstance(message, BinaryMessage):
        if message.header.message_id != _MESSAGE_ID:
            raise ProtocolError("Expected MATCHEDPOSB message ID 96")
        values: bytes | tuple[str, ...] = message.payload
    elif isinstance(message, AsciiMessage) and message.name == "MATCHEDPOSA":
        values = message.fields
    else:
        raise ProtocolError("Expected a MATCHEDPOS frame")
    record = BodyReader(values).read(_LAYOUT)
    return replace(record, name="MATCHEDPOS", message=message)


def matched_position_read(*, port: Port | None = None) -> Command[Record]:
    """Request one binary MATCHEDPOS frame."""
    request = logging.request("MATCHEDPOSB", port=port, message_id=_MESSAGE_ID)
    return Command(request.text, request.matches, decode_matched_position)


def matched_position_output(*, port: Port | None = None) -> Command[CommandResponse]:
    """Subscribe to changes in the binary matched position."""
    return logging.output("MATCHEDPOSB", Trigger.ON_CHANGED, port=port)


def matched_position_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a previously started matched position subscription."""
    return logging.stop("MATCHEDPOSB", port=port)
