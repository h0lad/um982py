"""Decode RTCM station, observation and ephemeris messages into records."""

from um982py.errors import ProtocolError
from um982py.messages.frames import RtcmMessage
from um982py.messages.layouts.rtcm import (
    FIXED,
    GLO_HEADER,
    GPS_HEADER,
    MSM_CELLS,
    MSM_HEADER,
    MSM_TYPES,
    OBSERVATIONS,
    STATION,
    BitField,
)
from um982py.messages.record import Record, Value
from um982py.protocol.binary import parse_rtcm

STANDARD_RTCM_TYPES = frozenset(
    FIXED.keys() | OBSERVATIONS.keys() | MSM_TYPES | {1007, 1033}
)
UNICORE_RTCM_TYPES = frozenset({63, 1104, 1105})


class _Bits:
    def __init__(self, payload: bytes) -> None:
        self.value = int.from_bytes(payload, "big")
        self.remaining = len(payload) * 8

    def take(self, width: int) -> int:
        if width > self.remaining:
            raise ProtocolError("Truncated RTCM body")
        self.remaining -= width
        return (self.value >> self.remaining) & ((1 << width) - 1)

    def scalar(self, field: BitField) -> int | float:
        width = abs(field.bits)
        value = self.take(width)
        if field.bits < 0 and value & (1 << (width - 1)):
            value = (
                -(value & ((1 << (width - 1)) - 1))
                if field.sign_magnitude
                else value - (1 << width)
            )
        return value if field.scale == 1 else value * field.scale

    def fields(self, layout: tuple[BitField, ...]) -> list[tuple[str, Value]]:
        return [(field.name, self.scalar(field)) for field in layout]

    def text(self) -> tuple[int, str]:
        count = self.take(8)
        # Keep byte values reversible, including vendor strings outside ASCII.
        value = bytes(self.take(8) for _ in range(count)).decode("latin-1")
        return count, value

    def finish(self) -> None:
        if self.remaining >= 8:
            raise ProtocolError("Unexpected trailing RTCM body data")
        if self.take(self.remaining):
            raise ProtocolError("Nonzero RTCM padding")


def _descriptor(reader: _Bits, kind: int) -> list[tuple[str, Value]]:
    fields = reader.fields(STATION)
    count, description = reader.text()
    fields.extend((("DF029", count), ("DF030", description), ("DF031", reader.take(8))))
    if kind == 1033:
        for count_id, text_id in ((32, 33), (227, 228), (229, 230), (231, 232)):
            count, description = reader.text()
            fields.extend(
                ((f"DF{count_id:03}", count), (f"DF{text_id:03}", description))
            )
    return fields


def _observations(reader: _Bits, kind: int) -> list[tuple[str, Value]]:
    gps = kind < 1009
    fields = reader.fields(GPS_HEADER if gps else GLO_HEADER)
    count = Record("header", tuple(fields)).integer("DF006" if gps else "DF035")
    satellites = tuple(
        Record("satellite", tuple(reader.fields(OBSERVATIONS[kind])))
        for _ in range(count)
    )
    fields.append(("satellites", satellites))
    return fields


def _indices(mask: int, width: int) -> tuple[int, ...]:
    return tuple(i + 1 for i in range(width) if mask & (1 << (width - i - 1)))


def _columns(
    reader: _Bits,
    rows: list[list[tuple[str, Value]]],
    layout: tuple[BitField, ...],
) -> None:
    # MSM stores one column for every satellite/cell before the next field.
    for field in layout:
        for row in rows:
            row.append((field.name, reader.scalar(field)))


def _msm(reader: _Bits, kind: int) -> list[tuple[str, Value]]:
    family, subtype = divmod(kind, 10)
    fields = reader.fields(STATION)
    if family == 108:
        fields.extend((("DF416", reader.take(3)), ("DF034", reader.take(27))))
    else:
        epoch_id = {107: "DF004", 109: "DF248", 112: "DF427"}[family]
        fields.append((epoch_id, reader.take(30)))
    fields.extend(reader.fields(MSM_HEADER))
    header = Record("header", tuple(fields))
    satellite_ids = _indices(header.integer("DF394"), 64)
    signal_ids = _indices(header.integer("DF395"), 32)
    cell_mask = reader.take(len(satellite_ids) * len(signal_ids))
    pairs = [(sat, sig) for sat in satellite_ids for sig in signal_ids]
    active = _indices(cell_mask, len(pairs))
    if len(active) > 64:
        raise ProtocolError("RTCM MSM exceeds 64 active cells")
    satellite_rows: list[list[tuple[str, Value]]] = [
        [("satellite_id", sat)] for sat in satellite_ids
    ]
    cell_rows: list[list[tuple[str, Value]]] = [
        [("satellite_id", pairs[i - 1][0]), ("signal_id", pairs[i - 1][1])]
        for i in active
    ]
    satellite_layout: tuple[BitField, ...] = () if subtype == 3 else (BitField(397, 8),)
    if subtype in (5, 7):
        satellite_layout += (BitField(419 if family == 108 else "extended_info", 4),)
    satellite_layout += (BitField(398, 10, 2**-10),)
    if subtype in (5, 7):
        satellite_layout += (BitField(399, -14),)
    _columns(reader, satellite_rows, satellite_layout)
    _columns(reader, cell_rows, MSM_CELLS[subtype])
    fields.extend(
        (
            ("DF396", cell_mask),
            ("satellite_count", len(satellite_ids)),
            ("signal_count", len(signal_ids)),
            ("cell_count", len(active)),
            ("signal_ids", signal_ids),
            (
                "satellites",
                tuple(Record("satellite", tuple(row)) for row in satellite_rows),
            ),
            ("cells", tuple(Record("cell", tuple(row)) for row in cell_rows)),
        )
    )
    return fields


def decode_rtcm(data: bytes | RtcmMessage) -> Record:
    """Decode one RTCM frame, validating its checksum and complete body.

    The result preserves ``message_type`` and ``payload`` and adds ``status``
    and a ``fields`` Record. Standard data fields use DF identifiers and their
    scaled wire units. Repeated observations live in ``satellites`` and MSM
    ``cells`` records. MSM satellite and signal IDs are one-based mask indices.

    Observation epochs and MSM ranges remain milliseconds. Orbital angles use
    semicircles; angular harmonic corrections use radians. GLONASS vectors
    remain kilometres, and BDS group delays remain nanoseconds.
    Week numbers, channel codes and lock indicators retain their encoded
    values. Invalid measurement sentinels remain numeric; decoding alone does
    not establish observation validity or resolve time rollovers.

    Unknown types return ``unsupported`` with empty fields. Unicore private
    types return ``unicore_private``; 1104/1105 are not interpreted as SBAS MSM.
    Malformed supported bodies raise ProtocolError instead of falling back.
    """
    frame = parse_rtcm(data.raw if isinstance(data, RtcmMessage) else data)
    if isinstance(data, RtcmMessage) and frame != data:
        raise ProtocolError("RTCM frame metadata does not match its wire bytes")
    kind = frame.message_type
    if kind is None:
        raise ProtocolError("RTCM payload lacks a message type")
    fields: list[tuple[str, Value]] = []
    if kind in UNICORE_RTCM_TYPES:
        status = "unicore_private"
    elif kind not in STANDARD_RTCM_TYPES:
        status = "unsupported"
    else:
        reader = _Bits(frame.payload)
        if kind in FIXED:
            fields = reader.fields(FIXED[kind])
        elif kind in OBSERVATIONS:
            fields = _observations(reader, kind)
        elif kind in MSM_TYPES:
            fields = _msm(reader, kind)
        else:
            fields = _descriptor(reader, kind)
        reader.finish()
        status = "decoded"
    return Record(
        "RTCM",
        (
            ("message_type", kind),
            ("payload", frame.payload),
            ("status", status),
            ("fields", Record(f"RTCM{kind}", tuple(fields))),
        ),
        frame,
    )
