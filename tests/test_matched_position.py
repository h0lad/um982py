"""Validates MATCHEDPOS decoding against synthetic position frames."""

import struct

import pytest

from test_protocol import binary
from um982py.errors import ProtocolError
from um982py.experimental import decode_matched_position
from um982py.messages import AsciiMessage, LegacyAsciiHeader
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

LATITUDE = 52.520645
LONGITUDE = 13.409484
HEIGHT = 74.0

ASCII_FIELDS = (
    "SOL_COMPUTED",
    "NARROW_FLOAT",
    f"{LATITUDE:.8f}",
    f"{LONGITUDE:.8f}",
    f"{HEIGHT:.1f}",
    "48.0",
    "WGS84",
    "2.5",
    "2.5",
    "3.5",
    "0",
    "1.0",
    "2.0",
    "12",
    "10",
    "0",
    "0",
    "0",
    "0",
    "13",
    "33",
)


def binary_payload() -> bytes:
    """Pack one synthetic 72-byte matched position body."""
    return struct.pack(
        "<II3dfI3f4s2fBBBBBBBB",
        0,
        34,
        LATITUDE,
        LONGITUDE,
        HEIGHT,
        48.0,
        61,
        2.5,
        2.5,
        3.5,
        b"0\x00\x00\x00",
        1.0,
        2.0,
        12,
        10,
        0,
        0,
        0,
        0,
        0x13,
        0x33,
    )


def decode_binary(payload: bytes = b"") -> Record:
    """Decode a synthetic binary payload through the wire decoder."""
    (message,) = StreamDecoder(strict=True).feed(
        binary(payload or binary_payload(), message_id=96)
    )
    return decode_matched_position(message)


def decode_ascii(fields: tuple[str, ...] = ASCII_FIELDS) -> Record:
    """Decode synthetic ASCII fields without wire framing."""
    return decode_matched_position(
        AsciiMessage(LegacyAsciiHeader("MATCHEDPOSA", ()), fields, b"#MATCHEDPOSA")
    )


def test_binary_frame_decodes_to_named_position() -> None:
    record = decode_binary()
    assert record.name == "MATCHEDPOS"
    assert record.real("lat") == pytest.approx(LATITUDE)
    assert record.real("lon") == pytest.approx(LONGITUDE)
    assert record.real("hgt") == pytest.approx(HEIGHT)
    assert record.integer("count_svs") == 12


def test_ascii_frame_decodes_to_the_same_position() -> None:
    record = decode_ascii()
    assert record.name == "MATCHEDPOS"
    assert record.real("lat") == pytest.approx(LATITUDE, abs=1e-6)
    assert record.real("lon") == pytest.approx(LONGITUDE, abs=1e-6)
    assert record["pos_type"] == "NARROW_FLOAT"


def test_binary_and_ascii_frames_agree() -> None:
    binary_record = decode_binary()
    ascii_record = decode_ascii()
    for key in ("lat", "lon", "hgt", "lat_std", "lon_std", "hgt_std"):
        assert binary_record.real(key) == pytest.approx(
            ascii_record.real(key), abs=1e-4
        )


def test_wrong_message_id_is_rejected() -> None:
    (message,) = StreamDecoder(strict=True).feed(
        binary(binary_payload(), message_id=42)
    )
    with pytest.raises(ProtocolError, match="message ID 96"):
        decode_matched_position(message)


def test_truncated_binary_is_rejected() -> None:
    with pytest.raises(ProtocolError):
        decode_binary(binary_payload()[:70])


def test_foreign_frames_are_rejected() -> None:
    (message,) = StreamDecoder(strict=True).feed(
        binary(binary_payload(), message_id=96)
    )
    assert decode_matched_position(message).name == "MATCHEDPOS"
    other = AsciiMessage(LegacyAsciiHeader("BESTPOSA", ()), ASCII_FIELDS, b"")
    with pytest.raises(ProtocolError, match="Expected a MATCHEDPOS frame"):
        decode_matched_position(other)
