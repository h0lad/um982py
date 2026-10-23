"""Validates RTKDATA decoding against synthetic engine frames."""

import struct

import pytest

from test_protocol import binary
from um982py.errors import ProtocolError
from um982py.experimental import RtkData, decode_rtk_data
from um982py.messages.enums import MessageSatelliteSystem
from um982py.protocol import StreamDecoder

ENTRY = struct.Struct("<III")


def payload(
    entries: tuple[tuple[int, int, int], ...], matrix: tuple[float, ...] = ()
) -> bytes:
    """Frame synthetic entries behind a fixed header and covariance."""
    values = tuple(matrix) + (0.0,) * (9 - len(matrix))
    header = bytes(108)
    body = struct.pack("<9f", *values)
    framed = header[:28] + body + header[28 + 36 :]
    return framed + b"".join(ENTRY.pack(*entry) for entry in entries)


def decode(data: bytes, message_id: int = 215) -> RtkData:
    """Decode a synthetic binary payload through the wire decoder."""
    (message,) = StreamDecoder(strict=True).feed(binary(data, message_id=message_id))
    return decode_rtk_data(message)


def test_frame_decodes_matrix_and_satellites() -> None:
    record = decode(
        payload(
            ((10, 5, 0), (78, 15, 0), (168, 5, 0), (250, 70, 0)),
            (45.801, 2.914, 9.572, 2.914, 44.613, -18.225, 9.572, -18.225, 111.597),
        )
    )
    assert record.name == "RTKDATA"
    assert record.covariance == pytest.approx(
        (45.801, 2.914, 9.572, 2.914, 44.613, -18.225, 9.572, -18.225, 111.597)
    )
    assert [(sat.system, sat.prn) for sat in record.satellites] == [
        (MessageSatelliteSystem.GPS, 10),
        (MessageSatelliteSystem.GALILEO, 4),
        (MessageSatelliteSystem.BEIDOU, 8),
        (None, None),
    ]
    assert [sat.satellite_id for sat in record.satellites] == [10, 78, 168, 250]
    assert [sat.status for sat in record.satellites] == [5, 15, 5, 70]
    assert [sat.value for sat in record.satellites] == [0, 0, 0, 0]
    assert len(record.header_fields_raw) == 108


def test_secondary_variant_decodes_with_own_name() -> None:
    record = decode(payload(((32, 5, 0),)), message_id=2027)
    assert record.name == "RTKDATA2"
    assert [(sat.system, sat.prn) for sat in record.satellites] == [
        (MessageSatelliteSystem.GPS, 32)
    ]


def test_empty_satellite_list_decodes() -> None:
    record = decode(payload(()))
    assert record.satellites == ()
    assert record.covariance == pytest.approx((0.0,) * 9)


def test_wrong_message_id_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="message ID 215"):
        decode(payload(((10, 5, 0),)), message_id=43)


def test_truncated_and_misaligned_frames_are_rejected() -> None:
    with pytest.raises(ProtocolError, match="body length"):
        decode(payload(((10, 5, 0),))[:100])
    with pytest.raises(ProtocolError, match="body length"):
        decode(payload(((10, 5, 0),)) + b"\x00")


def test_non_finite_covariance_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="Non-finite"):
        decode(payload(((10, 5, 0),), (float("nan"),)))
