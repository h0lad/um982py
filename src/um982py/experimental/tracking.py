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


_RF_GROUPS = (
    "GPS L1 C/A",
    "GPS L2C",
    "GLONASS G1",
    "GLONASS G2",
    "BeiDou B1I",
    "BeiDou B3I",
    "Galileo E1 (unverified)",
    "Galileo E5b",
    "Galileo E5a",
)
"""Bank-slot RF groups, matched against RANGE and RANGEH."""


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

    @property
    def antenna(self) -> int:
        """Antenna of the bank: bank 0 is ANT1 and bank 1 is ANT2."""
        return self.bank + 1

    @property
    def rf_group(self) -> str:
        """RF signal group of the bank slot in the standard signal mode."""
        return (
            _RF_GROUPS[self.bank_slot]
            if self.bank_slot < len(_RF_GROUPS)
            else "unknown"
        )

    @property
    def reference_cn0_db_hz(self) -> float | None:
        """Reference C/N0 of this antenna and RF group, or ``None`` when empty.

        The value equalled, to 0.01 dB, the mean C/N0 of the three or four
        strongest satellites of the group in RANGE (ANT1) or RANGEH (ANT2) at
        the same epoch, for both antennas. The number
        of averaged satellites varied between captures, and the Galileo E1
        slot did not match better than 0.16 dB. A drop across a whole group
        on one antenna points at interference rather than a single-satellite
        fade.
        """
        if not self.written or not self.native_value > 0:
            return None
        return self.native_value

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
    """The native message metadata stays on the original frame. The decoded
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
