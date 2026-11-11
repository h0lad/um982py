"""Decode one complete receiver message from its wire bytes."""

from typing import TYPE_CHECKING

from um982py.commands.catalog import RTCM_LOGS
from um982py.errors import ProtocolError
from um982py.messages.decode import decode_log
from um982py.messages.frames import (
    AsciiMessage,
    BinaryMessage,
    LogListMessage,
    Message,
    RtcmMessage,
    Sentence,
)
from um982py.messages.record import Record
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import (
    BINARY_SYNC,
    LEGACY_BINARY_SYNC,
    parse_binary,
    parse_rtcm,
)
from um982py.protocol.listing import listing_size, parse_listing

if TYPE_CHECKING:
    from um982py.commands import Log


def _frame(raw: bytes) -> Message:
    if not raw:
        raise ProtocolError("Expected one receiver message")
    if raw.startswith((BINARY_SYNC, LEGACY_BINARY_SYNC)):
        return parse_binary(raw)
    if raw.startswith(b"\xd3"):
        return parse_rtcm(raw)
    if raw.startswith(b"#UNILOGLIST,") and b"*" not in raw.split(b"\n", 1)[0]:
        if listing_size(bytearray(raw)) != len(raw):
            raise ProtocolError("Expected one complete UNILOGLIST response")
        return parse_listing(raw)
    if not raw.startswith((b"$", b"#")):
        raise ProtocolError("Unknown receiver message header")
    body = raw.rstrip(b"\r\n")
    if raw[len(body) :] not in (b"", b"\n", b"\r\n") or b"\n" in body or b"\r" in body:
        raise ProtocolError("Expected exactly one ASCII message")
    return parse_ascii(raw)


def decode_message(raw: bytes, *, log: "Log | None" = None) -> Record:
    """Decode one receiver message, optionally selecting its log type.

    The decoder validates checksums when present. Give ``log`` when several
    binary logs share a message ID. Unsupported messages and ambiguous binary
    IDs raise ``ProtocolError``.
    """
    from um982py.commands import Log

    frame = _frame(raw)
    if log is not None:
        if not isinstance(log, Log):
            raise TypeError("log must be a Log")
        return log.decode(frame)
    if isinstance(frame, (Sentence, RtcmMessage, LogListMessage)):
        return decode_log(frame)
    if isinstance(frame, (BinaryMessage, AsciiMessage)):
        binary = isinstance(frame, BinaryMessage)
        matches = []
        for candidate in Log:
            try:
                wire = candidate.wire_name(binary=binary)
            except ValueError:
                continue
            if isinstance(frame, BinaryMessage):
                if candidate.value in RTCM_LOGS:
                    continue
                if candidate.definition.message_id == frame.header.message_id:
                    matches.append(candidate)
            elif wire == frame.name:
                matches.append(candidate)
        if len(matches) == 1:
            return matches[0].decode(frame)
        if len(matches) > 1:
            names = ", ".join(candidate.value for candidate in matches)
            raise ProtocolError(f"Ambiguous message ({names}); specify log")
    raise ProtocolError("Unknown or unsupported data log")
