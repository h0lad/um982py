"""Unicore binary and RTCM frame parsing."""

from struct import Struct

from um982py.errors import ChecksumError, ProtocolError
from um982py.messages.frames import (
    BinaryHeader,
    BinaryMessage,
    OemBinaryHeader,
    RtcmMessage,
)
from um982py.protocol.checksums import rtcm_crc24q, unicore_crc32

BINARY_SYNC = b"\xaa\x44\xb5"
OEM_BINARY_SYNC = b"\xaa\x44\x12"
BINARY_HEADER = Struct("<3sBHHBBHIIBBH")


def parse_binary(raw: bytes) -> BinaryMessage:
    if raw.startswith(OEM_BINARY_SYNC):
        if len(raw) < 32 or raw[3] < 28:
            raise ProtocolError("Invalid OEM-style binary header")
        length = int.from_bytes(raw[8:10], "little")
        if len(raw) != raw[3] + length + 4:
            raise ProtocolError("OEM-style binary length mismatch")
        if unicore_crc32(raw[:-4]) != int.from_bytes(raw[-4:], "little"):
            raise ChecksumError("OEM-style binary CRC mismatch")
        oem_header = OemBinaryHeader(
            int.from_bytes(raw[4:6], "little"), length, raw[: raw[3]]
        )
        return BinaryMessage(oem_header, raw[raw[3] : -4], raw)
    if len(raw) < BINARY_HEADER.size + 4 or not raw.startswith(BINARY_SYNC):
        raise ProtocolError("Invalid N4 binary header")
    fields = BINARY_HEADER.unpack_from(raw)
    header = BinaryHeader(*fields[1:])
    if len(raw) != BINARY_HEADER.size + header.payload_length + 4:
        raise ProtocolError("N4 binary length mismatch")
    if unicore_crc32(raw[:-4]) != int.from_bytes(raw[-4:], "little"):
        raise ChecksumError("N4 binary CRC mismatch")
    return BinaryMessage(header, raw[BINARY_HEADER.size : -4], raw)


def parse_rtcm(raw: bytes) -> RtcmMessage:
    if len(raw) < 6 or raw[0] != 0xD3 or raw[1] & 0xFC:
        raise ProtocolError("Invalid RTCM3 header")
    length = ((raw[1] & 3) << 8) | raw[2]
    if len(raw) != length + 6:
        raise ProtocolError("RTCM3 length mismatch")
    if rtcm_crc24q(raw[:-3]) != int.from_bytes(raw[-3:], "big"):
        raise ChecksumError("RTCM3 CRC mismatch")
    payload = raw[3:-3]
    message_type = int.from_bytes(payload[:2], "big") >> 4 if length >= 2 else None
    return RtcmMessage(message_type, payload, raw)
