"""Raw baseband container and inner-message framing."""

from dataclasses import dataclass
from struct import Struct, unpack_from
from typing import Self

from um982py.errors import ChecksumError, ProtocolError
from um982py.experimental.baseband_messages import (
    BasebandMessageSpec,
    decode_message_payload,
)
from um982py.experimental.baseband_messages import spec as message_spec
from um982py.messages.record import Record

HEADER_SIZE = 0x14
"""Bytes of container header with native field names."""

FIRST_MESSAGE_OFFSET = 0x30
"""Offset of the first inner message."""

PROLOGUE_SIZE = FIRST_MESSAGE_OFFSET - HEADER_SIZE
"""Bytes between the named header and the first inner message."""

CHECKSUM_SIZE = 4
MIN_LENGTH = 0x35
DEFAULT_MAX_LENGTH = 0x4000
"""The receiver reads at most this many bytes per baseband FIFO transfer."""

_HEADER = Struct("<IIIIBBH")
"""``sequence``, ``major_version``, ``sync_tag``, ``total_length``, then fields."""


@dataclass(frozen=True, slots=True)
class BasebandHeader:
    """The fields parsed from a container header."""

    sequence: int
    major_version: int
    measurement_sync_tag: int
    total_length: int
    antenna_id: int
    frequency_code: int
    interval: int

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        if len(data) < HEADER_SIZE:
            raise ProtocolError("Raw baseband container is shorter than its header")
        return cls(*_HEADER.unpack_from(data))


@dataclass(frozen=True, slots=True)
class BasebandMessage:
    """One framed message inside a container."""

    message_id: int
    declared_length: int
    header_size: int
    payload: bytes
    raw: bytes

    @property
    def spec(self) -> BasebandMessageSpec:
        """Return the catalogue entry for this message ID."""
        return message_spec(self.message_id)

    def decode(self) -> Record:
        """Decode the body with the extended layout for this message ID."""
        return decode_message_payload(self.message_id, self.payload)


DEFAULT_LAYOUT = (0x04, 0x02)
"""``(header_size, length_offset)`` used by most message IDs."""

SPECIAL_MESSAGE_ID = 0x93
"""Message ID whose length field sits at a different offset."""

SPECIAL_LAYOUT = (0x0C, 0x0A)
"""``(header_size, length_offset)`` used by :data:`SPECIAL_MESSAGE_ID`."""


def _message_layout(message_id: int) -> tuple[int, int]:
    """Return ``(header_size, length_offset)`` for a message ID."""
    return SPECIAL_LAYOUT if message_id == SPECIAL_MESSAGE_ID else DEFAULT_LAYOUT


def parse_messages(data: bytes, *, offset: int = 0) -> tuple[BasebandMessage, ...]:
    """Frame a message region, rejecting truncated entries."""
    if offset < 0:
        raise ValueError("offset must be non-negative")
    messages = []
    cursor = 0
    while cursor < len(data):
        remaining = len(data) - cursor
        if remaining < 4:
            raise ProtocolError(
                f"Truncated baseband message header at offset {offset + cursor}"
            )
        message_id = data[cursor]
        header_size, length_offset = _message_layout(message_id)
        if remaining < header_size:
            raise ProtocolError(
                f"Truncated baseband message {message_id} header at "
                f"offset {offset + cursor}"
            )
        declared = unpack_from("<H", data, cursor + length_offset)[0]
        if declared < header_size:
            raise ProtocolError(
                f"Baseband message {message_id} declares length {declared} "
                f"at offset {offset + cursor}"
            )
        if declared > remaining:
            raise ProtocolError(
                f"Baseband message {message_id} length {declared} exceeds the "
                f"{remaining} bytes at offset {offset + cursor}"
            )
        raw = bytes(data[cursor : cursor + declared])
        messages.append(
            BasebandMessage(
                message_id,
                declared,
                header_size,
                raw[header_size:],
                raw,
            )
        )
        cursor += declared
    return tuple(messages)


@dataclass(frozen=True, slots=True)
class RawBasebandPacket:
    """A validated baseband container."""

    declared_length: int
    checksum: int
    raw: bytes

    @property
    def header(self) -> BasebandHeader:
        return BasebandHeader.from_bytes(self.raw)

    @property
    def sequence(self) -> int:
        return self.header.sequence

    @property
    def major_version(self) -> int:
        return self.header.major_version

    @property
    def measurement_sync_tag(self) -> int:
        """Return the native measurement tag, whose time scale is not established."""
        return self.header.measurement_sync_tag

    @property
    def antenna_id(self) -> int:
        return self.header.antenna_id

    @property
    def frequency_code(self) -> int:
        """Return the native code without assuming a carrier-frequency mapping."""
        return self.header.frequency_code

    @property
    def interval(self) -> int:
        """Return the native interval value, whose units remain unverified."""
        return self.header.interval

    @property
    def prologue(self) -> bytes:
        """Return the bytes ``0x14..0x2f``, whose meaning is not established."""
        return self.raw[HEADER_SIZE:FIRST_MESSAGE_OFFSET]

    @property
    def message_data(self) -> bytes:
        """Return the message bytes from ``0x30`` up to the trailing checksum word."""
        return self.raw[FIRST_MESSAGE_OFFSET:-CHECKSUM_SIZE]

    @property
    def messages(self) -> tuple[BasebandMessage, ...]:
        return parse_messages(self.message_data, offset=FIRST_MESSAGE_OFFSET)

    @property
    def content(self) -> bytes:
        """Return the opaque bytes between the named header and the checksum."""
        return self.raw[HEADER_SIZE:-CHECKSUM_SIZE]

    @property
    def checksum_coverage(self) -> bytes:
        """Return the bytes covered by the XOR checksum, ``(length - 4) & ~3``."""
        return self.raw[: (self.declared_length - CHECKSUM_SIZE) & ~3]

    @property
    def checksum_excluded(self) -> bytes:
        """Return the trailing partial word that the checksum does not cover."""
        end = (self.declared_length - CHECKSUM_SIZE) & ~3
        return self.raw[end:-CHECKSUM_SIZE]

    def manifest(self) -> dict[str, object]:
        return {
            "declared_length": self.declared_length,
            "checksum": f"0x{self.checksum:08x}",
            "sequence": self.sequence,
            "major_version": self.major_version,
            "measurement_sync_tag": self.measurement_sync_tag,
            "antenna_id": self.antenna_id,
            "frequency_code": self.frequency_code,
            "interval": self.interval,
            "message_ids": [message.message_id for message in self.messages],
        }

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Validate the length field and the XOR of complete words."""
        if len(data) < MIN_LENGTH:
            raise ProtocolError("Raw baseband container must exceed 52 bytes")
        header = BasebandHeader.from_bytes(data)
        if header.total_length < MIN_LENGTH:
            raise ProtocolError("Raw baseband container length is below 53 bytes")
        if header.total_length != len(data):
            raise ProtocolError("Raw baseband container length mismatch")
        checksum = unpack_from("<I", data, header.total_length - CHECKSUM_SIZE)[0]
        actual = 0
        end = (header.total_length - CHECKSUM_SIZE) & ~3
        for (word,) in Struct("<I").iter_unpack(data[:end]):
            actual ^= word
        if actual != checksum:
            raise ChecksumError("Raw baseband container XOR mismatch")
        return cls(header.total_length, checksum, bytes(data))

    @classmethod
    def build(
        cls,
        *,
        sequence: int = 0,
        major_version: int = 0,
        measurement_sync_tag: int = 0,
        antenna_id: int = 0,
        frequency_code: int = 0,
        interval: int = 0,
        prologue: bytes = b"",
        content: bytes = b"",
    ) -> Self:
        """Build a consistent container for tests and tooling."""
        if len(prologue) > PROLOGUE_SIZE:
            raise ValueError(f"prologue must be at most {PROLOGUE_SIZE} bytes")
        for name, value in (
            ("sequence", sequence),
            ("major_version", major_version),
            ("measurement_sync_tag", measurement_sync_tag),
            ("antenna_id", antenna_id),
            ("frequency_code", frequency_code),
            ("interval", interval),
        ):
            if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{name} must be an unsigned 32-bit integer")
        if antenna_id > 0xFF or frequency_code > 0xFF:
            raise ValueError("antenna_id and frequency_code must be bytes")
        if interval > 0xFFFF:
            raise ValueError("interval must be an unsigned 16-bit integer")
        prologue = prologue.ljust(PROLOGUE_SIZE, b"\0")
        length = HEADER_SIZE + PROLOGUE_SIZE + len(content) + CHECKSUM_SIZE
        if length < MIN_LENGTH:
            raise ValueError(
                "A valid container needs at least one content byte before the checksum"
            )
        header = _HEADER.pack(
            sequence,
            major_version,
            measurement_sync_tag,
            length,
            antenna_id,
            frequency_code,
            interval,
        )
        raw = bytearray(header + prologue + content + b"\0" * CHECKSUM_SIZE)
        checksum = 0
        end = (length - CHECKSUM_SIZE) & ~3
        for (word,) in Struct("<I").iter_unpack(bytes(raw[:end])):
            checksum ^= word
        raw[-CHECKSUM_SIZE:] = Struct("<I").pack(checksum)
        return cls.from_bytes(bytes(raw))


def build_message(
    message_id: int, payload: bytes = b"", *, header_size: int | None = None
) -> bytes:
    """Frame one inner message with the message length convention."""
    if not 0 <= message_id <= 0xFF:
        raise ValueError("message_id must be a byte")
    layout, length_offset = _message_layout(message_id)
    if header_size is None:
        header_size = layout
    if header_size < length_offset + 2:
        raise ValueError("header_size is too small for the length field")
    length = header_size + len(payload)
    if length > 0xFFFF:
        raise ValueError("baseband message is too long")
    frame = bytearray(header_size)
    frame[0] = message_id
    Struct("<H").pack_into(frame, length_offset, length)
    return bytes(frame) + bytes(payload)


class BasebandStream:
    """Parses containers from a byte stream and resynchronises after errors."""

    def __init__(
        self,
        *,
        max_length: int = DEFAULT_MAX_LENGTH,
        first_message_offset: int = FIRST_MESSAGE_OFFSET,
    ) -> None:
        if type(max_length) is not int or max_length < MIN_LENGTH:
            raise ValueError(f"max_length must be an integer >= {MIN_LENGTH}")
        if first_message_offset < HEADER_SIZE or first_message_offset % 4:
            raise ValueError("first_message_offset must be word aligned after header")
        self.max_length = max_length
        self.first_message_offset = first_message_offset
        self._buffer = bytearray()
        self.discarded = 0

    @property
    def pending(self) -> bytes:
        return bytes(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.discarded = 0

    def finish(self) -> bytes:
        """Return and clear bytes that cannot complete a retained candidate."""
        remainder = bytes(self._buffer)
        self._buffer.clear()
        return remainder

    def feed(self, data: bytes) -> tuple[RawBasebandPacket, ...]:
        self._buffer.extend(data)
        packets: list[RawBasebandPacket] = []
        while True:
            outcome = self._next()
            if outcome is None:
                return tuple(packets)
            packet, consumed = outcome
            packets.append(packet)
            del self._buffer[:consumed]

    def _next(self) -> tuple[RawBasebandPacket, int] | None:
        buffer = self._buffer
        scan = 0
        while scan + HEADER_SIZE <= len(buffer):
            declared = unpack_from("<I", buffer, scan + 12)[0]
            if not MIN_LENGTH <= declared <= self.max_length:
                scan += 1
                continue
            if scan + declared > len(buffer):
                later = self._valid_after(scan + 1)
                if later is None:
                    self._discard_prefix(scan)
                    return None
                scan = later
                continue
            try:
                packet = RawBasebandPacket.from_bytes(
                    bytes(buffer[scan : scan + declared])
                )
            except (ChecksumError, ProtocolError):
                scan += 1
                continue
            return packet, scan + declared
        self._keep_possible_partial_header()
        return None

    def _keep_possible_partial_header(self) -> None:
        """Discard everything that cannot be the start of a container."""
        keep = min(len(self._buffer), HEADER_SIZE - 1)
        self._discard_prefix(len(self._buffer) - keep)

    def _valid_after(self, start: int) -> int | None:
        buffer = self._buffer
        scan = start
        while scan + HEADER_SIZE <= len(buffer):
            declared = unpack_from("<I", buffer, scan + 12)[0]
            if MIN_LENGTH <= declared <= self.max_length and (
                scan + declared <= len(buffer)
            ):
                try:
                    RawBasebandPacket.from_bytes(bytes(buffer[scan : scan + declared]))
                except (ChecksumError, ProtocolError):
                    pass
                else:
                    return scan
            scan += 1
        return None

    def _discard_prefix(self, count: int) -> None:
        if count > 0:
            del self._buffer[:count]
            self.discarded += count


def scan_packets(
    data: bytes, *, max_length: int = DEFAULT_MAX_LENGTH
) -> tuple[RawBasebandPacket, ...]:
    """Return every complete container in ``data`` and ignore trailing bytes."""
    return BasebandStream(max_length=max_length).feed(data)
