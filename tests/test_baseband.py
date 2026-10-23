import random
from struct import pack, pack_into

import pytest

from conftest import acknowledgement
from test_protocol import binary
from um982py.dsp import DspCapture
from um982py.errors import ChecksumError, ProtocolError
from um982py.experimental import DebugOutput, bb_command, bb_debug, bb_log_enable
from um982py.experimental.baseband import (
    DEFAULT_MAX_LENGTH,
    FIRST_MESSAGE_OFFSET,
    HEADER_SIZE,
    MIN_LENGTH,
    BasebandHeader,
    BasebandStream,
    RawBasebandPacket,
    build_message,
    parse_messages,
    scan_packets,
)


def packet(
    *,
    messages: tuple[bytes, ...] = (),
    content: bytes | None = None,
    sequence: int = 7,
    major_version: int = 1,
    measurement_sync_tag: int = 0x11223344,
    antenna_id: int = 2,
    frequency_code: int = 9,
    interval: int = 10,
    prologue: bytes = b"",
) -> RawBasebandPacket:
    body = b"".join(messages) if content is None else content
    return RawBasebandPacket.build(
        sequence=sequence,
        major_version=major_version,
        measurement_sync_tag=measurement_sync_tag,
        antenna_id=antenna_id,
        frequency_code=frequency_code,
        interval=interval,
        prologue=prologue,
        content=body,
    )


def corrupt(raw: bytes, offset: int) -> bytes:
    data = bytearray(raw)
    data[offset] ^= 0xFF
    return bytes(data)


def test_header_fields_match_receiver_layout() -> None:
    raw = packet(content=b"\0")
    header = BasebandHeader.from_bytes(raw.raw)
    assert header == BasebandHeader(
        sequence=7,
        major_version=1,
        measurement_sync_tag=0x11223344,
        total_length=len(raw.raw),
        antenna_id=2,
        frequency_code=9,
        interval=10,
    )
    assert raw.header == header
    assert raw.sequence == 7
    assert raw.major_version == 1
    assert raw.measurement_sync_tag == 0x11223344
    assert raw.antenna_id == 2
    assert raw.frequency_code == 9
    assert raw.interval == 10
    assert HEADER_SIZE == 0x14
    assert FIRST_MESSAGE_OFFSET == 0x30
    assert MIN_LENGTH == 0x35


def test_short_header_rejected() -> None:
    with pytest.raises(ProtocolError):
        BasebandHeader.from_bytes(b"\0" * (HEADER_SIZE - 1))


def test_length_rules_follow_receiver_layout() -> None:
    raw = packet(messages=(build_message(0x10, b"\x01"),))
    with pytest.raises(ProtocolError, match="exceed 52"):
        RawBasebandPacket.from_bytes(b"\0" * (MIN_LENGTH - 1))
    shortened = bytearray(raw.raw)
    pack_into("<I", shortened, 12, MIN_LENGTH - 1)
    with pytest.raises(ProtocolError, match="below 53"):
        RawBasebandPacket.from_bytes(bytes(shortened))
    mismatched = bytearray(raw.raw)
    pack_into("<I", mismatched, 12, len(raw.raw) + 4)
    with pytest.raises(ProtocolError, match="length mismatch"):
        RawBasebandPacket.from_bytes(bytes(mismatched))


def test_checksum_error_is_distinct() -> None:
    raw = packet(messages=(build_message(0x10, b"\x01"),))
    with pytest.raises(ChecksumError):
        RawBasebandPacket.from_bytes(corrupt(raw.raw, 0))
    with pytest.raises(ChecksumError):
        RawBasebandPacket.from_bytes(corrupt(raw.raw, len(raw.raw) - 1))


def test_checksum_does_not_cover_trailing_partial_word() -> None:
    raw = packet(content=b"\x01\x02\x03\x04\x05")
    assert len(raw.raw) == FIRST_MESSAGE_OFFSET + 5 + 4
    assert len(raw.checksum_coverage) == (len(raw.raw) - 4) & ~3
    assert raw.checksum_excluded == b"\x05"
    # Changing the excluded byte must not affect the checksum.
    changed = bytearray(raw.raw)
    changed[-5] ^= 0xFF
    assert RawBasebandPacket.from_bytes(bytes(changed)).checksum == raw.checksum


def test_messages_use_two_header_layouts() -> None:
    default = build_message(0x10, b"\xaa\xbb")
    special = build_message(0x93, b"\x01\x02\x03")
    assert default == b"\x10\0\x06\0\xaa\xbb"
    assert special[0] == 0x93
    assert special[0x0A:0x0C] == pack("<H", 0x0C + 3)
    raw = packet(messages=(default, special))
    first, second = raw.messages
    assert (first.message_id, first.declared_length, first.header_size) == (
        0x10,
        6,
        4,
    )
    assert first.payload == b"\xaa\xbb"
    assert (second.message_id, second.declared_length, second.header_size) == (
        0x93,
        0x0F,
        0x0C,
    )
    assert second.payload == b"\x01\x02\x03"
    assert raw.manifest()["message_ids"] == [0x10, 0x93]


def test_message_region_and_prologue_are_separate() -> None:
    raw = packet(prologue=b"PROLOGUE", messages=(build_message(0x20, b"x"),))
    assert raw.raw[HEADER_SIZE:FIRST_MESSAGE_OFFSET] == b"PROLOGUE".ljust(0x1C, b"\0")
    assert raw.prologue.startswith(b"PROLOGUE")
    assert raw.message_data == raw.messages[0].raw
    assert raw.content.startswith(b"PROLOGUE")


@pytest.mark.parametrize(
    "data,message",
    [
        (b"\x10\0\x05\0", "exceeds"),
        (b"\x10\0\x03\0", "declares length"),
        (b"\x93\0\0\0", "Truncated baseband message 147"),
        (b"\x10\0", "Truncated baseband message header"),
    ],
)
def test_malformed_messages_raise(data: bytes, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        parse_messages(data, offset=0x30)


def test_empty_message_region_is_valid() -> None:
    raw = packet(messages=(build_message(0x10),))
    assert raw.messages[0].payload == b""
    assert parse_messages(b"") == ()
    assert RawBasebandPacket.from_bytes(raw.raw) == raw


def test_builder_validation() -> None:
    with pytest.raises(ValueError):
        RawBasebandPacket.build(sequence=-1)
    with pytest.raises(ValueError):
        RawBasebandPacket.build(antenna_id=256)
    with pytest.raises(ValueError):
        RawBasebandPacket.build(interval=0x10000)
    with pytest.raises(ValueError):
        RawBasebandPacket.build(prologue=b"x" * 0x1D)
    with pytest.raises(ValueError, match="content byte"):
        RawBasebandPacket.build()
    with pytest.raises(ValueError):
        build_message(0x100)
    with pytest.raises(ValueError):
        build_message(0x93, header_size=0x0A)


def test_stream_accepts_split_and_garbage() -> None:
    first = packet(messages=(build_message(0x10, b"a"),))
    second = packet(sequence=8, messages=(build_message(0x93, b"b"),))
    stream = BasebandStream()
    found = []
    for byte in b"noise" + first.raw + b"junk" + second.raw:
        found.extend(stream.feed(bytes([byte])))
    assert [item.raw for item in found] == [first.raw, second.raw]
    assert stream.pending == b""


def test_stream_resynchronises_past_false_candidate() -> None:
    fake = bytearray(60)
    pack_into("<I", fake, 12, 53)
    raw = packet(messages=(build_message(0x10, b"x"),))
    found = scan_packets(bytes(fake) + raw.raw)
    assert len(found) == 1
    assert found[0].raw == raw.raw


def test_stream_keeps_incomplete_candidate() -> None:
    raw = packet(messages=(build_message(0x10, b"x" * 8),))
    stream = BasebandStream()
    assert stream.feed(raw.raw[:FIRST_MESSAGE_OFFSET]) == ()
    assert stream.feed(raw.raw[FIRST_MESSAGE_OFFSET:-1]) == ()
    found = stream.feed(raw.raw[-1:])
    assert len(found) == 1
    assert found[0].raw == raw.raw


def test_stream_rejects_out_of_range_length_and_finishes() -> None:
    stream = BasebandStream()
    bogus = bytearray(24)
    pack_into("<I", bogus, 12, DEFAULT_MAX_LENGTH + 1)
    assert stream.feed(bytes(bogus)) == ()
    assert stream.discarded > 0
    assert stream.finish() != b""
    assert stream.pending == b""
    with pytest.raises(ValueError):
        BasebandStream(max_length=MIN_LENGTH - 1)
    with pytest.raises(ValueError):
        BasebandStream(first_message_offset=HEADER_SIZE + 1)


def test_scan_packets_ignores_trailing_garbage() -> None:
    raw = packet(messages=(build_message(0x10, b"x"),))
    found = scan_packets(raw.raw + b"tail")
    assert [item.raw for item in found] == [raw.raw]


def test_baseband_commands() -> None:
    assert bb_command("$BBLOGEN,0").text == "BBCMD $BBLOGEN,0"
    assert bb_log_enable(0).text == "BBCMD $BBLOGEN,00000000"
    assert bb_log_enable(0xFFFFFFFF).text == "BBCMD $BBLOGEN,FFFFFFFF"
    assert bb_debug(enabled=True).text == "BBDEBUG ON"
    assert bb_debug(enabled=False).text == "BBDEBUG OFF"
    assert DebugOutput.BASEBAND_PACKETS.output(1).text == "RAWBBPKG 1"
    assert DebugOutput.BASEBAND_PACKETS.on_changed().text == "RAWBBPKG ONCHANGED"
    assert DebugOutput.BASEBAND_PACKETS.stop().text == "UNLOG RAWBBPKG"
    assert DebugOutput.BASEBAND_NOTICE.on_changed().text == "BBNOTICE ONCHANGED"
    with pytest.raises(ValueError, match="ONCHANGED"):
        DebugOutput.BASEBAND_NOTICE.output(1)
    assert DebugOutput.BASEBAND_PACKETS.carries_baseband_containers
    assert not DebugOutput.SAMPLE_DATA.carries_baseband_containers
    for invalid in ("BBLOGEN,0", "$" + "X" * 127, "$A\nB", "$A*B"):
        with pytest.raises(ValueError):
            bb_command(invalid)
    with pytest.raises(ValueError):
        bb_log_enable(-1)
    with pytest.raises(ValueError):
        bb_debug(enabled=1)  # type: ignore[arg-type]


def test_dsp_capture_exposes_baseband_packets() -> None:
    raw = packet(messages=(build_message(0x10, b"\x01\x02"),))
    capture = DspCapture.from_bytes(
        binary(raw.raw, message_id=65500) + acknowledgement("RAWBBPKG 1")
    )
    assert len(capture.frames) == 1
    assert capture.frames[0].baseband == (raw,)
    assert capture.baseband_packets == (raw,)
    manifest = capture.manifest()
    assert manifest["baseband_packets"] == 1
    assert manifest["frames"][0]["baseband"][0]["sequence"] == 7


def test_build_and_validate_round_trip_for_random_sizes() -> None:
    rng = random.Random(1234)  # noqa: S311 - deterministic test data
    for size in range(1, 65):
        content = bytes(rng.randrange(256) for _ in range(size))
        raw = RawBasebandPacket.build(content=content)
        parsed = RawBasebandPacket.from_bytes(raw.raw)
        assert parsed.raw == raw.raw
        assert parsed.header == raw.header
        assert len(parsed.checksum_coverage) == (len(parsed.raw) - 4) & ~3
        changed = bytearray(raw.raw)
        changed[-1] ^= 0xFF
        with pytest.raises(ChecksumError):
            RawBasebandPacket.from_bytes(bytes(changed))


def test_stream_recovers_packets_between_random_garbage() -> None:
    rng = random.Random(5678)  # noqa: S311 - deterministic test data
    packets = [
        packet(sequence=index, messages=(build_message(0x10, bytes([index])),))
        for index in range(6)
    ]
    blob = bytearray()
    for item in packets:
        blob.extend(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40))))
        blob.extend(item.raw)
    blob.extend(b"tail")
    found = scan_packets(bytes(blob))
    assert [item.raw for item in found] == [item.raw for item in packets]
