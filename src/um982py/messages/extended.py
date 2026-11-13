"""Decode extended receiver log bodies."""

import re
from dataclasses import replace

from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record
from um982py.messages.layouts.firmware import LAYOUTS
from um982py.messages.reader import BodyReader


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
    return replace(BodyReader(values).read(LAYOUTS[name]), message=message)


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
