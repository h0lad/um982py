"""Decode one complete receiver message from its wire bytes."""

from typing import TYPE_CHECKING

from um982py.errors import ProtocolError
from um982py.messages.decode import decode_log
from um982py.messages.frames import Message
from um982py.messages.record import Record
from um982py.protocol.decoder import FRAME_STARTS, StreamDecoder

if TYPE_CHECKING:
    from um982py.commands import Log


def _frame(raw: bytes) -> Message:
    """Frame exactly one message with the stream decoder's strict rules."""
    if not raw:
        raise ProtocolError("Expected one receiver message")
    if not raw.startswith(FRAME_STARTS):
        raise ProtocolError("Unknown receiver message header")
    decoder = StreamDecoder(strict=True)
    messages = decoder.feed(raw)
    if not messages and b"\n" not in raw:
        # Complete a single ASCII line given without its line end.
        messages = decoder.feed(b"\r\n")
    if len(messages) != 1 or decoder.pending:
        raise ProtocolError("Expected exactly one receiver message")
    return messages[0]


def decode_message(raw: bytes, *, log: Log | None = None) -> Record:
    """The decoder validates checksums when present. Give ``log`` when several
    binary logs share a message ID. Unsupported messages and ambiguous binary
    IDs raise ``ProtocolError``.
    """
    frame = _frame(raw)
    return decode_log(frame, log=log)
