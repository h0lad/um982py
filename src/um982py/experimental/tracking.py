"""Neutral typed fields from a tracking diagnostic record."""

from dataclasses import dataclass

from um982py.experimental.layouts import LAYOUTS
from um982py.messages import Record
from um982py.messages.schema import Field

__all__ = ["TrackingField", "TrackingSlot", "tracking_fields", "tracking_slots"]


@dataclass(frozen=True, slots=True)
class TrackingField:
    """A diagnostic field with its wire offset and storage type."""

    name: str
    offset: int
    storage: str
    value: int | float


@dataclass(frozen=True, slots=True)
class TrackingSlot:
    """A diagnostic slot, not a satellite or an average."""

    slot: int
    bank: int
    bank_slot: int
    written: bool
    native_value: float


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
    """Expose PTOBSINFO values without assigning unverified physical meanings."""
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
