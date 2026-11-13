"""Version and firmware information models."""

import re
from dataclasses import dataclass
from typing import Self

from um982py.errors import ProtocolError
from um982py.messages.frames import AsciiMessage, BinaryMessage, Message
from um982py.messages.record import Record

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
    71: "UMD982C",
    94: "UM982A",
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
        from um982py.commands import Log
        from um982py.messages.decode import decode_log

        if not (
            (
                isinstance(message, AsciiMessage)
                and message.name in ("VERSION", "VERSIONA")
            )
            or (isinstance(message, BinaryMessage) and message.header.message_id == 37)
        ):
            raise ProtocolError("Not a VERSION message")
        return cls.from_record(decode_log(message, log=Log.VERSION))

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Build version information from a decoded VERSION record."""
        if record.name != "VERSION":
            raise ProtocolError("Not a VERSION record")
        try:
            model_id = record["type"]
            if isinstance(model_id, int):
                model = _MODEL_NAMES.get(model_id, str(model_id))
            elif isinstance(model_id, str):
                model = model_id
            elif model_id is None:
                model = ""
            else:
                raise TypeError("Invalid model")
            values = []
            for key in ("sw_version", "auth", "psn", "efuse_id", "comp_time"):
                value = record[key]
                if value is None:
                    value = ""
                if not isinstance(value, str):
                    raise TypeError(f"Invalid {key}")
                values.append(value)
            return cls(model, *values)
        except (KeyError, TypeError) as error:
            raise ProtocolError("Invalid VERSION record") from error
