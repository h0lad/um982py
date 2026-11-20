"""Receive and export the UM982 BINEX observation stream."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import BinexMessage, CommandResponse, Message
from um982py.protocol.binex import frame_binex_observations


@dataclass(frozen=True, slots=True)
class BinexEpoch:
    """Time tag and satellite count reported in a BINEX observation epoch."""

    time_tag_ms: int
    time_system: int
    satellite_count: int
    receiver_clock_offset_ns: int | None
    clock_reset_flag: int | None
    system_offsets_ns: tuple[tuple[int, int], ...]

    @property
    def gps_epoch_s(self) -> float | None:
        """Return absolute GPST seconds for a GPS-referenced epoch."""
        return self.time_tag_ms / 1000 if self.time_system == 0 else None


@dataclass(frozen=True, slots=True)
class BinexSatellite:
    """A satellite's native ID, observation count and encoded signal blocks."""

    prn: int
    system: int
    observation_count: int
    unhealthy: bool
    raw: bytes


def _epoch_header(message: BinexMessage) -> tuple[BinexEpoch, int]:
    data = message.payload
    if len(data) < 8 or data[0] != 5:
        raise ProtocolError("Incomplete BINEX observation header")
    minutes = int.from_bytes(data[1:5], "big")
    milliseconds = int.from_bytes(data[5:7], "big")
    if milliseconds >= 60_000:
        raise ProtocolError("BINEX time tag is outside its minute")
    flags = data[7]
    cursor = 8
    clock_offset = reset = None
    time_system = 0
    offsets: list[tuple[int, int]] = []
    if flags & 0x80:
        if len(data) < cursor + 3:
            raise ProtocolError("Incomplete BINEX receiver clock field")
        word = int.from_bytes(data[cursor : cursor + 3], "big")
        reset = word >> 22
        clock_offset = (word & 0x1FFFFF) - (word & 0x200000)
        cursor += 3
    if flags & 0x40:
        if len(data) <= cursor:
            raise ProtocolError("Incomplete BINEX time system header")
        time_system = data[cursor] & 0x0F
        count = data[cursor] >> 4
        cursor += 1
        if len(data) < cursor + count * 4:
            raise ProtocolError("Incomplete BINEX system time offsets")
        for offset in range(cursor, cursor + count * 4, 4):
            value = int.from_bytes(data[offset : offset + 3], "big", signed=True)
            offsets.append((data[offset + 3] & 0x0F, value))
        cursor += count * 4
    epoch = BinexEpoch(
        minutes * 60_000 + milliseconds,
        time_system,
        (flags & 0x3F) + 1,
        clock_offset,
        reset,
        tuple(offsets),
    )
    return epoch, cursor


def binex_epoch(message: BinexMessage) -> BinexEpoch:
    """Decode the epoch header, including its optional clock fields."""
    return _epoch_header(message)[0]


def _observation_end(data: bytes, cursor: int, *, reference: bool) -> int:
    more_flags = bool(data[cursor] & 0x80)
    cursor += 1
    format_flags = 0
    for _ in range(4):
        if not more_flags:
            break
        flag = data[cursor]
        cursor += 1
        more_flags = bool(flag & 0x80)
        if flag & 3 == 0:
            format_flags = flag
    if more_flags:
        raise ProtocolError("Too many BINEX observation flag bytes")
    # SNR and phase are fixed-width, followed by optional Doppler and slip count.
    range_size = 5 if reference else 3 if format_flags & 0x40 else 2
    cursor += 1 + range_size + 3
    if format_flags & 0x04:
        cursor += 3
    if format_flags & 0x08:
        cursor += 2 if format_flags & 0x10 else 1
    if cursor > len(data):
        raise ProtocolError("Truncated BINEX observation")
    return cursor


def _satellites(data: bytes, cursor: int, count: int) -> tuple[BinexSatellite, ...]:
    satellites = []
    try:
        for _ in range(count):
            start = cursor
            prn, flags = data[cursor], data[cursor + 1]
            cursor += 2
            observations = (flags >> 4) & 7
            for index in range(observations):
                cursor = _observation_end(data, cursor, reference=index == 0)
            satellites.append(
                BinexSatellite(
                    prn, flags & 15, observations, bool(flags & 128), data[start:cursor]
                )
            )
    except IndexError as error:
        raise ProtocolError("Truncated BINEX satellite block") from error
    if cursor != len(data):
        raise ProtocolError("Trailing bytes after BINEX satellite blocks")
    return tuple(satellites)


def binex_satellites(message: BinexMessage) -> tuple[BinexSatellite, ...]:
    """Extract the satellite blocks, retaining the encoded signal measurements."""
    epoch, start = _epoch_header(message)
    return _satellites(message.payload, start, epoch.satellite_count)


def binex_output(
    interval: float | Trigger = 1.0, *, port: Port | None = None
) -> Command[CommandResponse]:
    """Subscribe to BINEX7F05 observations."""
    return logging.output("BINEX7F05", interval, port=port)


def binex_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a BINEX7F05 subscription."""
    return logging.stop("BINEX7F05", port=port)


def write_binex(
    messages: Iterable[Message], stream: BinaryIO, *, drop_zero_prn: bool = False
) -> int:
    """Export BINEX frames and return their count.

    Use ``drop_zero_prn`` to remove invalid satellite-number-zero blocks and
    rebuild the affected frames for downstream readers.
    """
    count = 0
    for message in messages:
        if not isinstance(message, BinexMessage):
            continue
        raw = message.raw
        if drop_zero_prn:
            epoch, start = _epoch_header(message)
            satellites = _satellites(message.payload, start, epoch.satellite_count)
            valid = tuple(block.raw for block in satellites if block.prn)
            if not valid:
                continue
            if len(valid) != len(satellites):
                header = bytearray(message.payload[:start])
                header[7] = (header[7] & 0xC0) | (len(valid) - 1)
                raw = frame_binex_observations(bytes(header) + b"".join(valid))
        stream.write(raw)
        count += 1
    return count
