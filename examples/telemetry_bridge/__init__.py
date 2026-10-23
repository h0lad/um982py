"""Streams every decoded frame as newline-delimited JSON."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from um982py.errors import ProtocolError
from um982py.messages import (
    AsciiMessage,
    BinaryMessage,
    CommandResponse,
    LogListMessage,
    Message,
    Record,
    RtcmMessage,
    Sentence,
    Value,
    decode_log,
)


class FrameKind(StrEnum):
    """Protocol family that carried a frame."""

    NMEA = "nmea"
    UNICORE_ASCII = "unicore_ascii"
    UNICORE_BINARY = "unicore_binary"
    RTCM = "rtcm"
    UNILOGLIST = "uniloglist"
    COMMAND = "command"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class TelemetryFrame:
    """One frame with its identity and its decoded fields."""

    kind: FrameKind
    name: str
    message_id: int | None
    payload_length: int | None
    record: Record | None

    @property
    def decoded(self) -> bool:
        """True when the library has a body layout for this frame."""
        return self.record is not None

    def to_object(self) -> dict[str, object]:
        """Plain dictionary with the type, the identity and the fields."""
        return {
            "type": self.kind.value,
            "name": self.name,
            "message_id": self.message_id,
            "payload_length": self.payload_length,
            "fields": None if self.record is None else record_object(self.record),
        }

    def to_line(self) -> str:
        """Encode the frame as a single JSON line without a terminator."""
        return json.dumps(self.to_object(), separators=(",", ":"), default=str)


def value_object(value: Value) -> object:
    """Convert one record value into a JSON-serialisable object."""
    if isinstance(value, Record):
        return record_object(value)
    if isinstance(value, tuple):
        return [value_object(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def record_object(record: Record) -> dict[str, object]:
    """Convert a record into a plain dictionary, keeping field order."""
    return {key: value_object(value) for key, value in record.entries}


def decode_frame(message: Message) -> Record | None:
    """Decode a frame body, or ``None`` when no layout is documented for it."""
    try:
        return decode_log(message)
    except ProtocolError:
        return None


def frame_from(message: Message) -> TelemetryFrame:
    """Classify one frame and attach the fields the library decodes."""
    record = decode_frame(message)
    if isinstance(message, BinaryMessage):
        header = message.header
        name = record.name if record is not None else f"message_{header.message_id}"
        return TelemetryFrame(
            FrameKind.UNICORE_BINARY,
            name,
            header.message_id,
            header.payload_length,
            record,
        )
    if isinstance(message, RtcmMessage):
        return TelemetryFrame(
            FrameKind.RTCM, f"RTCM_{message.message_type}", None, None, record
        )
    if isinstance(message, LogListMessage):
        return TelemetryFrame(FrameKind.UNILOGLIST, "UNILOGLIST", None, None, record)
    if isinstance(message, CommandResponse):
        return TelemetryFrame(FrameKind.COMMAND, message.command, None, None, record)
    if isinstance(message, AsciiMessage):
        return TelemetryFrame(FrameKind.UNICORE_ASCII, message.name, None, None, record)
    if isinstance(message, Sentence):
        return TelemetryFrame(FrameKind.NMEA, message.name, None, None, record)
    return TelemetryFrame(FrameKind.TEXT, "text", None, None, record)


def lines(frames: Iterable[Message]) -> tuple[str, ...]:
    """Encode every frame as one JSON line, in arrival order."""
    return tuple(frame_from(frame).to_line() for frame in frames)


__all__ = [
    "FrameKind",
    "TelemetryFrame",
    "decode_frame",
    "frame_from",
    "lines",
    "record_object",
    "value_object",
]
