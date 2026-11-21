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

# Each entry gives the native code and the required masked status value.
_STANDARD_SIGNALS = (
    (0x00, 0x400, 0),
    (0x08, 0x100, 0x100),
    (0x34, 0, 0),
    (0x3C, 0, 0),
    (0x22, 0, 0),
    (0x2A, 0, 0),
    (0x03, 0, 0),
    (0x1B, 0, 0),
    (0x13, 0, 0),
)
_ALTERNATE_SIGNALS = (
    None,
    None,
    None,
    None,
    (0x22, 0, 0),
    (0x2A, 0, 0),
    (0x02, 0, 0),
    (0x1A, 0x400, 0x400),
    (0x12, 0, 0),
)


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

    def matches_rf_group(
        self, *, antenna: int, signal_code: int, status: int, mode: int
    ) -> bool:
        """Check the slot mapping for native group fields and receiver mode."""
        signals = _ALTERNATE_SIGNALS if mode in (11, 13, 14, 17) else _STANDARD_SIGNALS
        if self.bank != int(antenna == 1) or not 0 <= self.bank_slot < len(signals):
            return False
        mapping = signals[self.bank_slot]
        if mapping is None:
            return False
        code, mask, masked_status = mapping
        return signal_code == code and status & mask == masked_status


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
