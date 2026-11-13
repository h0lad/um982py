"""Decode extended receiver log bodies."""

from dataclasses import replace

from um982py.errors import ProtocolError
from um982py.firmware_layouts import LAYOUTS
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record
from um982py.messages.reader import BodyReader
from um982py.navigation_layouts import visibility_fields


def decode_extended(name: str, message: Message) -> Record:
    """Decode an extended log whose frame has already been matched."""
    if isinstance(message, BinaryMessage):
        values: bytes | tuple[str, ...] = message.payload
    elif isinstance(message, AsciiMessage):
        values = message.fields
        if name == "HEADINGOFFSET" and len(values) == 3 and values[-1] == "":
            values = values[:-1]
        if name == "SATVIS2":
            values = visibility_fields(values)
    else:
        raise ProtocolError("Expected an extended data log")
    return replace(BodyReader(values).read(LAYOUTS[name]), message=message)
