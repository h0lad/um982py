from dataclasses import replace

import pytest

from conftest import acknowledgement, ascii_message, rtcm, sentence
from um982py.errors import ChecksumError, ProtocolError
from um982py.messages import (
    AsciiMessage,
    CommandResponse,
    Sentence,
    TextLine,
)
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import BINARY_HEADER, parse_binary, parse_rtcm
from um982py.protocol.checksums import nmea_checksum, rtcm_crc24q, unicore_crc32


def binary(payload: bytes = b"\x00\n$#\xaaD\xb5", message_id: int = 65500) -> bytes:
    body = (
        BINARY_HEADER.pack(
            b"\xaaD\xb5",
            98,
            message_id,
            len(payload),
            0,
            200,
            2400,
            123000,
            2400,
            0,
            18,
            3,
        )
        + payload
    )
    return body + unicore_crc32(body).to_bytes(4, "little")


def test_independent_checksum_vectors() -> None:
    assert nmea_checksum(b"RESET") == 0x55
    assert unicore_crc32(b"123456789") == 0x2DFD2D88
    assert rtcm_crc24q(b"123456789") == 0xCDE703
    assert unicore_crc32(b"") == rtcm_crc24q(b"") == nmea_checksum(b"") == 0


@pytest.mark.parametrize(
    "data", [binary(), rtcm(b"\x3e\xd0\n$#"), sentence(b"GPGGA,1,2")]
)
def test_mixed_stream(data: bytes) -> None:
    decoder = StreamDecoder(strict=True)
    messages = decoder.feed(
        b"noise" + data + acknowledgement("VERSION") + b"plain text\r\n"
    )
    assert len(messages) == 3
    assert isinstance(messages[-1], TextLine)
    assert decoder.discarded_bytes == 5


def test_control_checksums_differ_from_nmea() -> None:
    assert parse_ascii(b"$command,VERSION,response: OK*04\r\n").accepted
    assert isinstance(parse_ascii(b"$CONFIG,MASK,MASK 5.0*25\r\n"), Sentence)
    assert isinstance(parse_ascii(b"$GNRMC,,V,,,,,,,,,,N,V*37\r\n"), Sentence)
    response = parse_ascii(acknowledgement("CONFIG COM1 921600", "UNKNOWN COMMAND"))
    assert isinstance(response, CommandResponse)
    assert not response.accepted


@pytest.mark.parametrize("command", ["RAWDATAB RANGEB 1", "RAWDATAA RANGEA 1"])
def test_live_missing_colon_rejection(command: str) -> None:
    # This response was captured from a UM982.
    raw = f"$command,{command},response can't found device (null)*31\r\n".encode()
    decoder = StreamDecoder(strict=True)
    (response,) = decoder.feed(raw)
    assert isinstance(response, CommandResponse)
    assert response.command == command
    assert response.status == "can't found device (null)"
    assert response.raw == raw
    assert not response.accepted
    assert not decoder.errors and decoder.discarded_bytes == 0
    with pytest.raises(ChecksumError):
        parse_ascii(raw.replace(b"*31", b"*30"))


def test_response_separator_is_required() -> None:
    body = b"$command,VERSION,responseOK"
    raw = body + f"*{nmea_checksum(body):02X}\r\n".encode()
    with pytest.raises(ProtocolError, match="Malformed ASCII"):
        parse_ascii(raw)


@pytest.mark.parametrize(
    "raw", [b"$A", b"$A*GG\n", b"$A*1234\n", b"$A*00\n", b"#A*00000000\n", b"#A*00\n"]
)
def test_invalid_ascii(raw: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_ascii(raw)


def test_bad_ascii_header_and_csv() -> None:
    for fields in (
        b"X,1;data",
        b"X,no,GPS,FINE,1,1,1,0,18,0;data",
        b'X,1,GPS,FINE,1,1,1,0,18,0;"unterminated',
    ):
        raw = b"#" + fields + f"*{unicore_crc32(fields):08x}\r\n".encode()
        with pytest.raises(ProtocolError):
            parse_ascii(raw)


def test_model_frame_properties() -> None:
    message = parse_ascii(sentence(b"GNGGA,1,2"))
    assert isinstance(message, Sentence)
    assert message.talker == "GN" and message.kind == "GGA"
    ascii_frame = parse_ascii(ascii_message("UNKNOWN", '"a,b",,x'))
    assert isinstance(ascii_frame, AsciiMessage)
    assert ascii_frame.name == "UNKNOWN"
    assert ascii_frame.fields == ("a,b", "", "x")
    frame = parse_binary(binary())
    assert frame.header.message_id == 65500
    assert frame.payload == b"\x00\n$#\xaaD\xb5"
    assert replace(frame, payload=b"").raw == frame.raw


@pytest.mark.parametrize("raw", [b"", b"\xaaD\xb5", binary()[:-1], binary() + b"x"])
def test_binary_bad_length(raw: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_binary(raw)


def test_bad_binary_checksums_and_recovery() -> None:
    for valid in (
        binary(),
        binary(b"x" * 8),
        rtcm(b"\x3e\xd0"),
    ):
        bad = valid[:-1] + bytes([valid[-1] ^ 1])
        parser = parse_rtcm if valid.startswith(b"\xd3") else parse_binary
        with pytest.raises(ChecksumError):
            parser(bad)
        decoder = StreamDecoder()
        messages = decoder.feed(bad + b"\n" + acknowledgement("VERSION"))
        assert any(isinstance(m, CommandResponse) for m in messages)
        assert decoder.errors
        decoder.reset()
        assert (
            not decoder.pending and not decoder.errors and not decoder.discarded_bytes
        )
        with pytest.raises(ProtocolError):
            StreamDecoder(strict=True).feed(bad)


@pytest.mark.parametrize("payload", [b"", b"x", b"\x3e\xd0", b"x" * 1023])
def test_rtcm(payload: bytes) -> None:
    frame = parse_rtcm(rtcm(payload))
    assert frame.payload == payload
    assert frame.message_type == (
        int.from_bytes(payload[:2], "big") >> 4 if len(payload) >= 2 else None
    )


@pytest.mark.parametrize("raw", [b"", b"\xd3\xfc\0\0\0\0", rtcm(b"x")[:-1]])
def test_rtcm_invalid(raw: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_rtcm(raw)


def test_decoder_bounds_and_partial_headers() -> None:
    with pytest.raises(ValueError):
        StreamDecoder(max_frame_size=27)
    for partial in (b"\xaa", b"\xaaD", b"\xaaD\xb5\0", b"\xd3", b"\xd3\0"):
        decoder = StreamDecoder()
        assert not decoder.feed(partial)
        assert decoder.pending == partial
    decoder = StreamDecoder(max_frame_size=64)
    assert not decoder.feed(b"x" * 1000)
    assert len(decoder.pending) <= 64
    assert len(decoder.errors) <= 32
    decoder.feed(binary(b"x" * 65) + b"\n")
    assert decoder.errors
    decoder.feed(b"\xaaD\x12\x01" + b"\0" * 28)
    assert decoder.errors
    assert all(
        isinstance(message, TextLine)
        for message in StreamDecoder().feed(b"\xaaD\x01\n\xd3\xfc\0\n")
    )


def test_oversize_ascii_and_invalid_legacy() -> None:
    with pytest.raises(ProtocolError):
        StreamDecoder(strict=True, max_frame_size=28).feed(b"x" * 29 + b"\n")
    with pytest.raises(ProtocolError):
        parse_binary(b"\xaaD\x12\x01" + b"\0" * 28)
    with pytest.raises(ProtocolError):
        parse_binary(binary()[:-1])


def test_eof_and_reset() -> None:
    decoder = StreamDecoder()
    decoder.finish()
    decoder.feed(b"\xaaD")
    with pytest.raises(ProtocolError, match="Incomplete"):
        decoder.finish()
    decoder.reset()
    assert not decoder.pending and not decoder.errors and not decoder.discarded_bytes
    decoder.finish()


@pytest.mark.parametrize(
    "following", [binary(), rtcm(b"\x3e\xd0"), acknowledgement("VERSION")]
)
def test_recovery_prefers_checked_frames(following: bytes) -> None:
    decoder = StreamDecoder()
    decoded = decoder.feed(b"$bad*00\r\n" + following)
    assert len(decoded) == 1 and decoded[0].raw == following


def test_recovery_to_legacy_and_incomplete_noise() -> None:
    raw = binary()
    decoder = StreamDecoder()
    assert decoder.feed(b"$bad*00\n" + raw)[0].raw == raw
    decoder = StreamDecoder()
    decoder.feed(b"$bad*00\n$incomplete")
    assert decoder.pending == b"$incomplete"
    decoder = StreamDecoder()
    decoder.feed(b"$bad*00\n\xaaDx" + b"\0" * 40 + b"\n")
    assert decoder.errors


def test_legacy_and_binary_short_crc() -> None:
    raw = binary()
    with pytest.raises(ChecksumError):
        parse_binary(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ChecksumError):
        parse_binary(binary()[:-1] + bytes([binary()[-1] ^ 1]))


@pytest.mark.parametrize(
    "suffix", [b"\nNOTCOUNT\n", b"\n< 31\n", b"\n< 1\nNOTENTRY\n", b"\n< 1\n<\xff\n"]
)
def test_invalid_multiline_loglist(suffix: bytes) -> None:
    with pytest.raises(ProtocolError):
        StreamDecoder(strict=True).feed(
            b"#UNILOGLIST,1,GPS,FINE,1,1,1,0,18,0;" + suffix
        )
    decoder = StreamDecoder()
    decoder.feed(b"#UNILOGLIST,1,GPS,FINE,1,1,1,0,18,0;" + suffix)
    assert decoder.errors


def test_multiline_loglist_bounds() -> None:
    decoder = StreamDecoder(strict=True, max_frame_size=64)
    with pytest.raises(ProtocolError):
        decoder.feed(b"#UNILOGLIST," + b"x" * 65)
    from um982py.protocol.listing import listing_size

    assert listing_size(bytearray(b"#UNILOGLIST,")) is None


def test_empty_ascii_payload() -> None:
    frame = parse_ascii(ascii_message("EMPTY", ""))
    assert isinstance(frame, AsciiMessage) and not frame.fields
