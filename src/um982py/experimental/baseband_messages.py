"""The inner message catalogue and payload decoder."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from struct import unpack_from
from types import MappingProxyType
from typing import cast

from um982py.errors import ProtocolError
from um982py.experimental._bbmsg_data import CATALOGUE_DATA, IGNORED_IDS
from um982py.messages.record import Record, Value

__all__ = [
    "CATALOGUE",
    "IGNORED_IDS",
    "BasebandField",
    "BasebandMessageFamily",
    "BasebandMessageSpec",
    "decode_message_payload",
    "spec",
]


class BasebandMessageFamily(StrEnum):
    """How the receiver processes one inner message."""

    PAYLOAD = "payload"
    """Reads a fixed set of payload fields."""

    DELEGATOR = "delegator"
    """Hands the payload to a helper rather than reading fields."""

    FLAG = "flag"
    """Updates receiver state without reading a payload field."""

    NOOP = "noop"
    """Takes no action and reports success."""

    IGNORED = "ignored"
    """Dropped without further processing."""

    UNKNOWN = "unknown"
    """Accepted without a classified payload layout."""


_FIELD_TYPES: dict[str, tuple[int, str]] = {
    "u8": (1, "<B"),
    "i8": (1, "<b"),
    "u16": (2, "<H"),
    "i16": (2, "<h"),
    "u32": (4, "<I"),
    "i32": (4, "<i"),
    "f32": (4, "<f"),
    "f64": (8, "<d"),
}

BYTES = "bytes"
"""Field type for an opaque byte range."""


@dataclass(frozen=True, slots=True)
class BasebandField:
    """One field read from a message payload."""

    offset: int
    size: int
    type: str
    name: str
    semantic: str = "unverified"

    def __post_init__(self) -> None:
        if self.type != BYTES and self.type not in _FIELD_TYPES:
            raise ValueError(f"Unsupported field type: {self.type!r}")
        if self.offset < 0 or self.size < 1:
            raise ValueError("Field offset must be non-negative and size positive")
        if self.type != BYTES and self.size != _FIELD_TYPES[self.type][0]:
            raise ValueError(
                f"Field {self.name} width {self.size} does not match {self.type}"
            )

    def read(self, payload: bytes) -> Value:
        """Read this field, raising :class:`ProtocolError` if it is truncated."""
        end = self.offset + self.size
        if end > len(payload):
            raise ProtocolError(
                f"Payload is {len(payload)} bytes; {self.name} needs {end}"
            )
        if self.type == BYTES:
            return bytes(payload[self.offset : end])
        (value,) = unpack_from(_FIELD_TYPES[self.type][1], payload, self.offset)
        return cast(Value, value)


@dataclass(frozen=True, slots=True)
class BasebandMessageSpec:
    """The layout and payload of one inner message ID."""

    message_id: int
    family: BasebandMessageFamily
    payload_extent: int | None = None
    """Smallest payload length that carries every described field."""

    repeating: bool = False
    """True when the field offsets describe only the first of several elements."""

    fields: tuple[BasebandField, ...] = ()

    @property
    def ignored(self) -> bool:
        return self.family is BasebandMessageFamily.IGNORED

    @property
    def classified(self) -> bool:
        """Return true when the message family is known."""
        return self.family is not BasebandMessageFamily.UNKNOWN

    @property
    def carries_fields(self) -> bool:
        return bool(self.fields)

    def decode(self, payload: bytes) -> Record:
        """Decode a payload into a ``Record``."""
        if self.ignored:
            return Record(f"message_{self.message_id}", ())
        if self.payload_extent is not None and len(payload) < self.payload_extent:
            raise ProtocolError(
                f"Message {self.message_id} needs {self.payload_extent} payload "
                f"bytes, got {len(payload)}"
            )
        return Record(
            f"message_{self.message_id}",
            tuple((field.name, field.read(payload)) for field in self.fields),
        )


def _catalogue() -> dict[int, BasebandMessageSpec]:
    built: dict[int, BasebandMessageSpec] = {}
    for entry in CATALOGUE_DATA:
        message_id, family, _size, extent, repeating, fields = entry
        built[message_id] = BasebandMessageSpec(
            message_id=message_id,
            family=BasebandMessageFamily(family),
            payload_extent=extent,
            repeating=repeating,
            fields=tuple(BasebandField(*field) for field in fields),
        )
    return built


CATALOGUE: Mapping[int, BasebandMessageSpec] = MappingProxyType(_catalogue())
"""Every inner message ID in the catalogue, keyed by message ID."""


def spec(message_id: int) -> BasebandMessageSpec:
    """Return the description for ``message_id``."""
    try:
        return CATALOGUE[message_id]
    except KeyError as error:
        raise ProtocolError(
            f"Message ID {message_id} is outside the catalogue range 19..203"
        ) from error


def decode_message_payload(message_id: int, payload: bytes) -> Record:
    """Decode an already-framed message payload by its message ID."""
    return spec(message_id).decode(payload)
