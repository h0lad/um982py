"""Decode extended receiver log bodies."""

import re
from dataclasses import replace
from struct import Struct

from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record
from um982py.messages.layouts.firmware import GLOALMANAC_ASCII, LAYOUTS
from um982py.messages.reader import BodyReader
from um982py.messages.record import Value
from um982py.messages.satellites import satellite_information

# The firmware renders these native bodies at fixed lengths.
_RAW_BODY_SIZES = {
    "BBPPSMSG": 108,
    "SBAS2": 116,
    "SBAS3": 116,
    "SBAS4": 116,
    "SBAS5": 116,
    "SBAS6": 228,
    "SBAS9": 104,
    "SBAS17": 108,
    "SBAS24": 132,
    "SBAS25": 132,
    "SBAS26": 144,
    "SBAS28": 56,
    "SBASALMANAC": 40,
}
_SSR_TABLE_SHAPES = {
    "SSR1ORBIT": (30, Struct("<Bi6d"), 12, 9, 2),
    "SSR1CLOCK": (28, Struct("<B3d"), 8, 7, 1),
}


def decode_extended(name: str, message: Message) -> Record:
    """Decode an extended log whose frame has already been matched."""
    if isinstance(message, BinaryMessage):
        values: bytes | tuple[str, ...] = message.payload
    elif isinstance(message, AsciiMessage):
        values = message.fields
        if name == "HEADINGOFFSET" and len(values) == 3 and values[-1] == "":
            values = values[:-1]
        if name == "SATVIS2":
            values = _visibility_fields(values)
    else:
        raise ProtocolError("Expected an extended data log")
    if name == "SATINFO":
        return replace(satellite_information(values), name=name, message=message)
    if name in _SSR_TABLE_SHAPES:
        return replace(_ssr_table(name, values), message=message)
    if name in _RAW_BODY_SIZES:
        if isinstance(values, bytes) and len(values) != _RAW_BODY_SIZES[name]:
            raise ProtocolError(f"Invalid {name} body size")
        key = "payload" if isinstance(values, bytes) else "fields"
        return Record(name, ((key, values),), message)
    if name == "GLOALMANAC":
        if isinstance(values, tuple):
            return replace(BodyReader(values).read(GLOALMANAC_ASCII), message=message)
        record = BodyReader(values).read(LAYOUTS[name])
        return Record(
            name,
            (
                record.entries[0],
                ("reference_tow_s", record.integer("reference_tow_s") / 1000),
                *record.entries[2:],
            ),
            message,
        )
    return replace(BodyReader(values).read(LAYOUTS[name]), message=message)


def _ssr_entry(values: tuple[int | float, ...], integer_fields: int) -> Record:
    fields: tuple[tuple[str, Value], ...] = (("satellite_id", values[0]),)
    if integer_fields == 2:
        fields += (("native_field", values[1]),)
    return Record("satellite", (*fields, ("coefficients", values[integer_fields:])))


def _ssr_table(name: str, values: bytes | tuple[str, ...]) -> Record:
    prefix_size, entry, ascii_prefix, count_index, integer_fields = _SSR_TABLE_SHAPES[
        name
    ]
    if isinstance(values, tuple):
        if len(values) < ascii_prefix:
            raise ProtocolError(f"Truncated {name} ASCII header")
        count = int(values[count_index])
        BodyReader.bound(count, 64)
        width = 8 if integer_fields == 2 else 4
        if len(values) != ascii_prefix + count * width:
            raise ProtocolError(f"Invalid {name} ASCII count")
        satellites = tuple(
            _ssr_entry(
                (
                    *(int(value) for value in values[offset : offset + integer_fields]),
                    *(
                        float(value)
                        for value in values[offset + integer_fields : offset + width]
                    ),
                ),
                integer_fields,
            )
            for offset in range(ascii_prefix, len(values), width)
        )
        return Record(
            name, (("fields", values), ("count", count), ("satellites", satellites))
        )
    if len(values) < prefix_size:
        raise ProtocolError(f"Truncated {name} binary header")
    stride = entry.size
    count = int.from_bytes(values[24:28], "little")
    BodyReader.bound(count, 64)
    end = prefix_size + stride * count
    if len(values) not in (end, prefix_size + stride * 64):
        raise ProtocolError(f"Invalid {name} count or body size")
    entries = tuple(
        values[offset : offset + stride] for offset in range(prefix_size, end, stride)
    )
    return Record(
        name,
        (
            ("count", count),
            ("native_header", values[:prefix_size]),
            ("native_entries", entries),
            ("native_tail", values[end:]),
            (
                "satellites",
                tuple(_ssr_entry(entry.unpack(raw), integer_fields) for raw in entries),
            ),
        ),
    )


def _visibility_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Expand SATVIS2's PRN[+/-channel] ASCII token into its binary field order."""
    try:
        count = int(fields[3])
        BodyReader.bound(count, 240)
        if len(fields) != 4 + count * 6:
            raise ProtocolError("SATVIS2 count does not match its fields")
        tokens = list(fields[:4])
        for index in range(count):
            start = 4 + index * 6
            satellite = re.fullmatch(r"(\d+)([+-]\d+)?", fields[start])
            if satellite is None:
                raise ProtocolError("Invalid SATVIS2 satellite ID")
            tokens.extend((satellite[2] or "0", satellite[1]))
            tokens.extend(fields[start + 1 : start + 6])
        return tuple(tokens)
    except (IndexError, ValueError) as error:
        raise ProtocolError("Invalid SATVIS2 count") from error
