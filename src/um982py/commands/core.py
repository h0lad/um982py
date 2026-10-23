"""The command value type and argument helpers."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from um982py.messages.frames import CommandResponse, Message
from um982py.protocol.checksums import nmea_checksum


def token(value: str) -> str:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value) is None:
        raise ValueError(f"Invalid command token: {value!r}")
    return value.upper()


def number(value: float, minimum: float, maximum: float) -> str:
    if (
        isinstance(value, bool)
        or not isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"Expected a finite number in {minimum}..{maximum}")
    return format(value, ".15g")


def normalize(text: str) -> str:
    return " ".join(text.upper().split()).removeprefix("$")


@dataclass(frozen=True, slots=True)
class Command[T]:
    text: str
    matches: Callable[[Message], bool]
    decode: Callable[[Message], T]
    dollar_prefixed: bool = False

    def __post_init__(self) -> None:
        if not self.text or self.text != self.text.strip():
            raise ValueError("Command must be nonempty and trimmed")
        if any(not 32 <= ord(char) < 127 for char in self.text):
            raise ValueError("Command must contain printable ASCII only")
        if self.text.startswith("$") or any(
            char in self.text for char in ("*", "#", ";")
        ):
            raise ValueError("Command must not contain protocol delimiters")

    def encode(self, *, checksummed: bool = False) -> bytes:
        body = self.text.encode("ascii")
        if checksummed:
            body = b"$" + body + f"*{nmea_checksum(body):02X}".encode("ascii")
        elif self.dollar_prefixed:
            body = b"$" + body
        return body + b"\r\n"


def action(text: str, *, dollar_prefixed: bool = False) -> Command[CommandResponse]:
    def matches(message: Message) -> bool:
        return isinstance(message, CommandResponse) and normalize(
            message.command
        ) == normalize(text)

    def decode(message: Message) -> CommandResponse:
        if not isinstance(message, CommandResponse):
            raise TypeError("Expected a command response")
        return message

    return Command(text, matches, decode, dollar_prefixed=dollar_prefixed)
