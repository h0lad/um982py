"""NMEA, Unicore and RTCM checksums."""

from functools import reduce
from operator import xor
from zlib import crc32


def nmea_checksum(data: bytes) -> int:
    return reduce(xor, data, 0)


def unicore_crc32(data: bytes) -> int:
    return crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF


def rtcm_crc24q(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF
