"""Version and firmware information models."""

import re
from dataclasses import dataclass
from struct import unpack_from
from typing import Self

from um982py.errors import ProtocolError
from um982py.messages.frames import AsciiMessage, BinaryMessage, Message

_MODEL_NAMES = {
    0: "UNKNOWN",
    17: "UM982",
    18: "UM980",
    19: "UM960",
    24: "UM960L",
    26: "UM981",
    31: "UM981S",
    40: "UMD982",
    41: "UMD981",
    42: "UMD981S",
    43: "UM981C",
    52: "UB9A0",
    53: "UBD9A0",
    62: "UMD960",
    63: "UMD980",
    64: "UM980C",
    65: "UM982C",
}


@dataclass(frozen=True, slots=True)
class Version:
    model: str
    software: str
    authorization: str
    serial_number: str
    efuse_id: str
    compiled: str

    @property
    def build(self) -> int | None:
        match = re.search(r"(\d+)$", self.software)
        return int(match[1]) if match is not None else None

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if isinstance(message, AsciiMessage) and message.name in (
            "VERSION",
            "VERSIONA",
        ):
            if len(message.fields) != 6:
                raise ProtocolError("Expected six VERSION fields")
            return cls(*message.fields)
        if isinstance(message, BinaryMessage) and message.header.message_id == 37:
            if len(message.payload) != 308:
                raise ProtocolError("Expected 308-byte VERSION payload")
            model_id = unpack_from("<I", message.payload)[0]
            try:
                values = tuple(
                    message.payload[start:end].split(b"\0", 1)[0].decode("ascii")
                    for start, end in (
                        (4, 37),
                        (37, 166),
                        (166, 232),
                        (232, 265),
                        (265, 308),
                    )
                )
            except UnicodeDecodeError as error:
                raise ProtocolError("Invalid VERSION text") from error
            return cls(_MODEL_NAMES.get(model_id, str(model_id)), *values)
        raise ProtocolError("Not a VERSION message")
