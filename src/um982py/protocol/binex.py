"""Framing for forward-readable big-endian BINEX observation records."""

from binascii import crc_hqx

from um982py.errors import ChecksumError, ProtocolError
from um982py.messages.frames import BinexMessage
from um982py.protocol.checksums import nmea_checksum

BINEX_SYNC = b"\xe2\x7f"


def _bounds(data: bytes | bytearray) -> tuple[int, int, int] | None:
    """Return the payload bounds and total size once the length is available."""
    if len(data) < len(BINEX_SYNC):
        return None
    if not data.startswith(BINEX_SYNC):
        raise ProtocolError("Expected a forward BINEX 0x7f record")
    length = 0
    for index, byte in enumerate(data[2:6], start=2):
        if index == 5:
            length = (length << 8) | byte
        else:
            length = (length << 7) | (byte & 0x7F)
            if byte & 0x80:
                continue
        start = index + 1
        end = start + length
        if length < 8 or end - 1 >= 4096:
            raise ProtocolError("Unsupported BINEX record length")
        checksum_size = 1 if end - 1 < 128 else 2
        return start, end, end + checksum_size
    return None


def binex_frame_size(data: bytes | bytearray) -> int | None:
    bounds = _bounds(data)
    return None if bounds is None else bounds[2]


def _checksum(data: bytes) -> bytes:
    if len(data) < 128:
        return bytes([nmea_checksum(data)])
    return crc_hqx(data, 0).to_bytes(2, "big")


def parse_binex(raw: bytes) -> BinexMessage:
    """Validate the record length, checksum and observation subrecord ID."""
    bounds = _bounds(raw)
    if bounds is None or bounds[2] != len(raw):
        raise ProtocolError("Incomplete or overlong BINEX record")
    start, end, _ = bounds
    if raw[end:] != _checksum(raw[1:end]):
        raise ChecksumError("BINEX checksum mismatch")
    if raw[start] != 0x05:
        raise ProtocolError("Expected BINEX observation subrecord 0x05")
    return BinexMessage(raw[start:end], raw)


def frame_binex_observations(payload: bytes) -> bytes:
    """Frame a 0x7f-05 body with its canonical length and a fresh checksum."""
    size = len(payload)
    if not 8 <= size <= 4092 or payload[0] != 5:
        raise ProtocolError("Unsupported BINEX observation payload")
    length = bytes([size]) if size < 128 else bytes([0x80 | (size >> 7), size & 0x7F])
    checked = BINEX_SYNC[1:] + length + payload
    return BINEX_SYNC[:1] + checked + _checksum(checked)
