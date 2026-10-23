"""Renders raw navigation-message bytes as annotated hexadecimal."""

from __future__ import annotations

from dataclasses import dataclass

from um982py.experimental.layouts import LAYOUTS as FIRMWARE_LAYOUTS
from um982py.messages.layouts import LAYOUTS as DOCUMENTED_LAYOUTS
from um982py.messages.record import Record, Value
from um982py.messages.schema import Field, Group, Layout

__all__ = [
    "FieldHex",
    "MessageHex",
    "annotate",
    "families",
    "field_span",
    "hex_bytes",
    "message_hex",
    "render_text",
    "satellite_of",
]

LAYOUTS: dict[str, Layout] = {**DOCUMENTED_LAYOUTS, **FIRMWARE_LAYOUTS}
"""Every decoded layout: documented logs plus extended ones."""

FAMILIES: tuple[tuple[str, str], ...] = (
    ("GPS", "GPSEPH"),
    ("GALILEO", "GALEPH"),
    ("BEIDOU", "BDSEPH"),
    ("BEIDOU-3", "BD3EPH"),
    ("GLONASS", "GLOEPH"),
    ("QZSS", "QZSSEPH"),
    ("NAVIC", "IRNSSEPH"),
)
"""Constellation and its binary ephemeris log name."""

SATELLITE_FIELD = ("prn", "satid", "sloto")
"""Field names that carry the satellite identifier, in preference order."""


def families() -> tuple[tuple[str, str], ...]:
    """Constellations that publish a decoded ephemeris layout."""
    return tuple((name, log) for name, log in FAMILIES if log in LAYOUTS)


PREFIXES = ("reserved", "field_", "unnamed", "trailing")
"""Field-name prefixes whose bytes are carried but not clearly documented."""


@dataclass(frozen=True, slots=True)
class FieldHex:
    """One span of the payload with the exact bytes it occupies."""

    name: str
    offset: int
    size: int
    raw: bytes
    value: Value
    documented: bool = True

    @property
    def hex(self) -> str:
        """Span bytes as lower-case hexadecimal."""
        return self.raw.hex()

    @property
    def end(self) -> int:
        """Offset one past the last byte."""
        return self.offset + self.size

    @property
    def reserved(self) -> bool:
        """True for reserved, neutral or unlabelled spans."""
        return not self.documented


@dataclass(frozen=True, slots=True)
class MessageHex:
    """One raw navigation message with its field annotation."""

    constellation: str
    log: str
    message_id: int
    satellite: int | None
    payload: bytes
    fields: tuple[FieldHex, ...]

    @property
    def header(self) -> bytes:
        """Message header bytes preceding the payload, when known."""
        return self.payload[:0]

    @property
    def hex(self) -> str:
        """Whole payload as lower-case hexadecimal."""
        return self.payload.hex()


def _documented(name: str) -> bool:
    return not name.startswith(PREFIXES)


def _group_size(group: Group, record: Record) -> int:
    if group.stride is not None:
        count = record[group.count] if isinstance(group.count, str) else group.count
        if isinstance(count, int):
            return group.stride * count
    inner = [entry for entry in group.fields if isinstance(entry, Field)]
    return max((entry.offset + entry.size for entry in inner), default=0)


def annotate(log: str, payload: bytes, record: Record) -> tuple[FieldHex, ...]:
    """Cover every payload byte, naming each span that the layout knows."""
    layout = LAYOUTS[log]
    planned: list[tuple[int, int, str, bool]] = []
    for entry in layout.fields:
        if isinstance(entry, Field):
            planned.append(
                (entry.offset, entry.size, entry.name, _documented(entry.name))
            )
        elif isinstance(entry, Group):
            planned.append((entry.offset, _group_size(entry, record), entry.name, True))
    planned.sort()
    spans: list[FieldHex] = []
    cursor = 0
    for offset, size, name, documented in planned:
        if cursor >= len(payload):
            break
        start = min(max(offset, cursor), len(payload))
        if start > cursor:
            spans.append(
                FieldHex(
                    f"unnamed_{cursor}",
                    cursor,
                    start - cursor,
                    bytes(payload[cursor:start]),
                    None,
                    False,
                )
            )
            cursor = start
        end = min(offset + size, len(payload))
        if start < end:
            spans.append(
                FieldHex(
                    name,
                    start,
                    end - start,
                    bytes(payload[start:end]),
                    _value(record, name),
                    documented,
                )
            )
            cursor = end
    if cursor < len(payload):
        spans.append(
            FieldHex(
                f"trailing_{cursor}",
                cursor,
                len(payload) - cursor,
                bytes(payload[cursor:]),
                None,
                False,
            )
        )
    return tuple(spans)


def _value(record: Record, name: str) -> Value:
    try:
        return record[name]
    except KeyError:
        return None


def satellite_of(record: Record) -> int | None:
    """Satellite identifier, or ``None`` for a non-satellite log."""
    for name in SATELLITE_FIELD:
        if name in record:
            return record.integer(name)
    return None


def field_span(log: str, field_name: str) -> tuple[int, int]:
    """Byte offset and size of a named field in a layout."""
    for entry in LAYOUTS[log].fields:
        if isinstance(entry, Field) and entry.name == field_name:
            return entry.offset, entry.size
    raise KeyError(f"{field_name} is not a scalar field of {log}")


def message_hex(
    constellation: str, log: str, message_id: int, payload: bytes, record: Record
) -> MessageHex:
    """Build the annotated view of one raw ephemeris message."""
    return MessageHex(
        constellation=constellation,
        log=log,
        message_id=message_id,
        satellite=satellite_of(record),
        payload=bytes(payload),
        fields=annotate(log, payload, record),
    )


def hex_bytes(data: bytes, width: int = 8) -> tuple[str, ...]:
    """Group bytes into fixed-width hexadecimal columns."""
    if width < 1:
        raise ValueError("width must be positive")
    return tuple(
        data[index : index + width].hex(" ").upper()
        for index in range(0, len(data), width)
    )


def render_text(message: MessageHex, *, width: int = 16) -> str:
    """Render one message as a field table followed by a hex dump."""
    reserved = sum(field.size for field in message.fields if field.reserved)
    lines = [
        f"{message.constellation} {message.log} "
        f"prn={'-' if message.satellite is None else message.satellite} "
        f"id={message.message_id} bytes={len(message.payload)} "
        f"reserved={reserved}",
        f"{'offset':>6} {'size':>4}  {'hex':<24} {'field':<24} value",
    ]
    for field in message.fields:
        value = field.value
        if value is None:
            shown = "-"
        elif isinstance(value, float):
            shown = f"{value:.12g}"
        else:
            shown = str(value)
        name = field.name if field.documented else f"{field.name} *"
        lines.append(
            f"{field.offset:6d} {field.size:4d}  {field.hex:<24} {name:<24} {shown}"
        )
    lines.append("")
    for offset in range(0, len(message.payload), width):
        chunk = message.payload[offset : offset + width]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:06X}  {chunk.hex(' '):<{width * 3 - 1}}  |{text}|")
    return "\n".join(lines)
