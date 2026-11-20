"""Neutral typed fields from a tracking diagnostic record."""

from dataclasses import dataclass

from um982py.errors import ProtocolError
from um982py.experimental.baseband import BasebandMessage
from um982py.messages import Record
from um982py.messages.layouts.firmware import LAYOUTS
from um982py.messages.reader import BodyReader
from um982py.messages.schema import Field

__all__ = [
    "TRACKING_MESSAGE_ID",
    "TrackingField",
    "TrackingSlot",
    "decode_tracking_message",
    "tracking_fields",
    "tracking_slots",
]

TRACKING_MESSAGE_ID = 24


@dataclass(frozen=True, slots=True)
class TrackingField:
    """A diagnostic field with its wire offset and storage type."""

    name: str
    offset: int
    storage: str
    value: int | float


@dataclass(frozen=True, slots=True)
class TrackingSlot:
    """A diagnostic slot with receiver-reported values."""

    slot: int
    bank: int
    bank_slot: int
    written: bool
    native_value: float


def decode_tracking_message(message: BasebandMessage) -> Record:
    """Read the PTOBSINFO body from an inner tracking message.

    The native message metadata stays on the original frame. The decoded
    record carries no serial log timestamp.
    """
    if message.message_id != TRACKING_MESSAGE_ID:
        raise ProtocolError("Expected baseband tracking message 24")
    # The copy starts at wire offset 16, 12 bytes into the framed payload.
    payload = message.decode()["field_12"]
    if not isinstance(payload, bytes):
        raise ProtocolError("Expected a binary PTOBSINFO body")
    return BodyReader(payload).read(LAYOUTS["PTOBSINFO"])


def tracking_slots(record: Record) -> tuple[TrackingSlot, ...]:
    """Decode the slot-write mask and the two nine-slot banks."""
    if record.name != "PTOBSINFO":
        raise ValueError("a PTOBSINFO record is required")
    mask = record.integer("field_11")
    return tuple(
        TrackingSlot(
            index,
            index // 9,
            index % 9,
            bool(mask & (1 << index)),
            record.real(f"field_{index + 12:02}"),
        )
        for index in range(18)
    )


def tracking_fields(record: Record) -> tuple[TrackingField, ...]:
    """Expose PTOBSINFO values using their native representation."""
    if record.name != "PTOBSINFO":
        raise ValueError("a PTOBSINFO record is required")
    tracked = []
    for field in LAYOUTS["PTOBSINFO"].fields:
        if not isinstance(field, Field):
            raise ValueError("unexpected tracking field layout")
        value = record[field.name]
        if not isinstance(value, (int, float)):
            raise ValueError("tracking field is not numeric")
        tracked.append(TrackingField(field.name, field.offset, field.kind, value))
    return tuple(tracked)
