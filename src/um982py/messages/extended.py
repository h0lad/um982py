"""Decode extended receiver log bodies."""

import re
from dataclasses import replace

from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record
from um982py.messages.layouts.firmware import GLOALMANAC_ASCII, LAYOUTS
from um982py.messages.reader import BodyReader
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
_SSR_TABLE_SHAPES = {"SSR1ORBIT": (30, 53), "SSR1CLOCK": (28, 25)}


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


def _ssr_table(name: str, values: bytes | tuple[str, ...]) -> Record:
    if isinstance(values, tuple):
        return Record(name, (("fields", values),))
    prefix_size, stride = _SSR_TABLE_SHAPES[name]
    count = int.from_bytes(values[24:28], "little")
    BodyReader.bound(count, 64)
    end = prefix_size + stride * count
    if len(values) not in (end, prefix_size + stride * 64):
        raise ProtocolError(f"Invalid {name} count or body size")
    return Record(
        name,
        (
            ("count", count),
            ("native_header", values[:prefix_size]),
            (
                "native_entries",
                tuple(
                    values[offset : offset + stride]
                    for offset in range(prefix_size, end, stride)
                ),
            ),
            ("native_tail", values[end:]),
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
