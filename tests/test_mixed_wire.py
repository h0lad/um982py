"""Regresses on mixed wire with unchecksummed text and binary frames."""

import pytest

from conftest import FIXTURES, acknowledgement
from test_protocol import binary
from um982py.errors import ChecksumError, ProtocolError
from um982py.experimental import BasebandCapture, scan_notices
from um982py.messages import BinaryMessage, TextLine
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii


@pytest.mark.parametrize("chunk", [1, 7, 65536])
def test_real_mixed_notices_do_not_steal_binary_bytes(chunk: int) -> None:
    raw = (FIXTURES / "baseband-notice.bin").read_bytes()
    decoder = StreamDecoder(strict=True)
    messages = []
    for offset in range(0, len(raw), chunk):
        messages.extend(decoder.feed(raw[offset : offset + chunk]))
    decoder.finish()
    assert not decoder.errors and decoder.discarded_bytes == 0
    binaries = [message for message in messages if isinstance(message, BinaryMessage)]
    assert [message.header.message_id for message in binaries] == [221] * 5
    text = [message for message in messages if isinstance(message, TextLine)]
    assert len(text) == 28
    assert all(not message.checksum_verified for message in text)
    notices = scan_notices(raw)
    headers = [notice.decode() for notice in notices if notice.name == "BBNOTICE"]
    assert [header.integer("string_size") for header in headers] == [552, 552, 216, 216]
    assert [header.integer("tag_count") for header in headers] == [
        12113,
        12114,
        12115,
        12116,
    ]
    assert all(
        header.integer("total_length") == header.integer("string_size") + 12
        and header.integer("board_type") == 35
        for header in headers
    )
    for header, expected_length in zip(
        (notice for notice in notices if notice.name == "BBNOTICE"),
        (543, 542, 211, 211),
        strict=True,
    ):
        start = raw.index(header.raw) + len(header.raw)
        following = raw.index(b"\xaaD\xb5", start)
        assert following - start == expected_length
    capture = BasebandCapture.from_bytes(raw)
    assert not capture.packets
    assert len(capture.notices) == 28
    assert capture.manifest()["normal_decoder_errors"] == []


def test_notice_text_exception_does_not_disable_checksum_validation() -> None:
    with pytest.raises(ProtocolError):
        parse_ascii(b"$GNGGA,missing_checksum\r\n")
    with pytest.raises(ChecksumError):
        parse_ascii(b"$NAVPOS,1*00\r\n")


def test_unchecked_text_inside_corrupt_binary_is_not_verified_resync() -> None:
    corrupt = bytearray(binary(b"$NAVPOS,1\r\n"))
    corrupt[-1] ^= 1
    decoder = StreamDecoder()
    messages = decoder.feed(bytes(corrupt) + acknowledgement("VERSION"))
    assert len(messages) == 1 and messages[0].raw == acknowledgement("VERSION")
    assert decoder.errors and decoder.discarded_bytes == len(corrupt)
