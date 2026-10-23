"""Builds synthetic native RANGE frames for the newer experiments."""

import struct

from tests.test_protocol import binary
from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.protocol import StreamDecoder
from um982py.protocol.checksums import unicore_crc32


def observation(
    *,
    signal: int = 0,
    system: int = 0,
    prn: int = 1,
    cn0: float = 45,
    code: float = 20_000_000,
    phase: float = 20_000_000,
    frequency: float = 1575.42e6,
    lock: float = 100,
    l2c: int = 0,
    channel: int = 7,
    valid: bool = True,
) -> bytes:
    """Pack independently assigned metre values into the documented native units."""
    status = (system << 16) | (signal << 21) | (l2c << 26) | (0x1400 if valid else 0)
    return struct.pack(
        "<HHdfdffffI",
        prn,
        channel,
        code,
        0.3,
        -phase * frequency / 299792458,
        0.01,
        0.0,
        cn0,
        lock,
        status,
    )


def wire(epoch: int, rows: list[bytes], *, secondary: bool = False) -> bytes:
    """Build a checksummed synthetic timestamped primary or secondary RANGE frame."""
    raw = bytearray(
        binary(struct.pack("<I", len(rows)) + b"".join(rows), 6005 if secondary else 43)
    )
    struct.pack_into("<I", raw, 12, 123000 + epoch * 1000)
    raw[-4:] = unicore_crc32(raw[:-4]).to_bytes(4, "little")
    return bytes(raw)


def record(epoch: int, rows: list[bytes], *, secondary: bool = False) -> Record:
    """Decode synthetic wire data using the library's native parser."""
    frame = StreamDecoder(strict=True).feed(wire(epoch, rows, secondary=secondary))[0]
    return (FirmwareLog.RANGEH if secondary else FirmwareLog.RANGE).decode(frame)
