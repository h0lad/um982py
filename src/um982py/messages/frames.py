"""Wire frame types for ASCII, binary and RTCM messages."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sentence:
    name: str
    fields: tuple[str, ...]
    raw: bytes

    @property
    def talker(self) -> str:
        return self.name[:2]

    @property
    def kind(self) -> str:
        return self.name[2:]


@dataclass(frozen=True, slots=True)
class AsciiHeader:
    name: str
    cpu_idle: int
    time_reference: str
    time_status: str
    week: int
    milliseconds: int
    version: int
    reserved: int
    leap_seconds: int
    delay_ms: int


@dataclass(frozen=True, slots=True)
class LegacyAsciiHeader:
    name: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AsciiMessage:
    header: AsciiHeader | LegacyAsciiHeader
    fields: tuple[str, ...]
    raw: bytes

    @property
    def name(self) -> str:
        return self.header.name


@dataclass(frozen=True, slots=True)
class BinaryHeader:
    cpu_idle: int
    message_id: int
    payload_length: int
    time_reference: int
    time_status: int
    week: int
    milliseconds: int
    version: int
    reserved: int
    leap_seconds: int
    delay_ms: int


@dataclass(frozen=True, slots=True)
class LegacyBinaryHeader:
    message_id: int
    payload_length: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class BinaryMessage:
    header: BinaryHeader | LegacyBinaryHeader
    payload: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class RtcmMessage:
    message_type: int | None
    payload: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class CommandResponse:
    command: str
    status: str
    raw: bytes

    @property
    def accepted(self) -> bool:
        return self.status.upper() == "OK"


@dataclass(frozen=True, slots=True)
class TextLine:
    raw: bytes

    @property
    def checksum_verified(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class LogListMessage:
    header: AsciiHeader | LegacyAsciiHeader
    entries: tuple[str, ...]
    raw: bytes

    @property
    def checksum_verified(self) -> bool:
        return False


type Message = (
    Sentence
    | AsciiMessage
    | BinaryMessage
    | RtcmMessage
    | CommandResponse
    | TextLine
    | LogListMessage
)
