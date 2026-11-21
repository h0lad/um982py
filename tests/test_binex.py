from binascii import crc_hqx
from io import BytesIO

import pytest

from test_protocol import binary
from um982py.binex import (
    BinexEphemerisType,
    binex_ephemeris_type,
    binex_epoch,
    binex_output,
    binex_satellites,
    binex_stop,
    write_binex,
)
from um982py.errors import ChecksumError, ProtocolError
from um982py.messages import BinaryMessage, BinexMessage
from um982py.protocol import StreamDecoder
from um982py.protocol.binex import frame_binex_observations, parse_binex


def _header(flags: int = 0) -> bytes:
    return b"\x05\x00\x00\x00\x01\x00\x14" + bytes([flags])


def _satellite(prn: int) -> bytes:
    return bytes([prn, 0x10, 1]) + bytes(9)


@pytest.mark.parametrize("chunk_size", [1, 7, 4096])
def test_binex_mixed_serial_stream(chunk_size: int) -> None:
    small = frame_binex_observations(_header() + _satellite(13))
    large = frame_binex_observations(_header(11) + _satellite(13) * 12)
    wire = small + binary() + large
    decoder = StreamDecoder(strict=True)
    messages = [
        frame
        for start in range(0, len(wire), chunk_size)
        for frame in decoder.feed(wire[start : start + chunk_size])
    ]
    decoder.finish()
    assert len(messages) == 3
    first, middle, last = messages
    assert isinstance(first, BinexMessage) and isinstance(last, BinexMessage)
    assert isinstance(middle, BinaryMessage)
    assert first.raw == small and last.raw == large
    assert binex_epoch(first).gps_epoch_s == 60.02
    assert binex_epoch(last).satellite_count == 12


def test_binex_recovers_next_checked_message_after_bad_crc() -> None:
    valid = frame_binex_observations(_header() + _satellite(13))
    broken = valid[:-1] + bytes([valid[-1] ^ 1])
    with pytest.raises(ChecksumError, match="BINEX"):
        parse_binex(broken)
    decoder = StreamDecoder()
    assert decoder.feed(broken + valid) == (parse_binex(valid),)
    assert len(decoder.errors) == 1


def test_clock_fields_preserve_signed_offsets_and_time_system() -> None:
    clock = ((1 << 22) | ((1 << 22) - 7)).to_bytes(3, "big")
    systems = b"\x13\xff\xff\xda\x01"
    message = parse_binex(
        frame_binex_observations(_header(0xC0) + clock + systems + _satellite(13))
    )
    epoch = binex_epoch(message)
    assert epoch.time_tag_ms == 60_020
    assert epoch.gps_epoch_s is None
    assert epoch.time_system == 3
    assert epoch.receiver_clock_offset_ns == -7
    assert epoch.clock_reset_flag == 1
    assert epoch.system_offsets_ns == ((1, -38),)


def test_export_removes_zero_prn_only_when_requested() -> None:
    retained = _satellite(13)
    wire = frame_binex_observations(_header(1) + _satellite(0) + retained)
    message = parse_binex(wire)
    original, compatible = BytesIO(), BytesIO()
    assert write_binex([message], original) == 1
    assert original.getvalue() == wire
    assert write_binex([message], compatible, drop_zero_prn=True) == 1
    rebuilt = parse_binex(compatible.getvalue())
    assert binex_epoch(rebuilt).satellite_count == 1
    (block,) = binex_satellites(rebuilt)
    assert (block.prn, block.system, block.observation_count, block.raw) == (
        13,
        0,
        1,
        retained,
    )


def test_incomplete_optional_and_satellite_fields_are_rejected() -> None:
    clock = parse_binex(frame_binex_observations(_header(0x80)))
    with pytest.raises(ProtocolError, match="clock field"):
        binex_epoch(clock)
    satellite = parse_binex(frame_binex_observations(_header() + _satellite(13)[:-1]))
    with pytest.raises(ProtocolError, match="Truncated BINEX observation"):
        binex_satellites(satellite)


def test_binex_commands_use_native_name() -> None:
    assert binex_output(1).text == "BINEX7F05 1"
    assert binex_stop().text == "UNLOG BINEX7F05"


@pytest.mark.parametrize("kind", list(BinexEphemerisType))
def test_binex_navigation_and_observations_share_a_stream(
    kind: BinexEphemerisType,
) -> None:
    payload = bytes([kind, 15]) + bytes(130)
    checked = b"\x01\x81\x04" + payload
    navigation = b"\xe2" + checked + crc_hqx(checked, 0).to_bytes(2, "big")
    observations = frame_binex_observations(_header() + _satellite(13))
    decoder = StreamDecoder(strict=True)
    wire = navigation + observations
    nav, obs = tuple(
        message for byte in wire for message in decoder.feed(bytes([byte]))
    )
    decoder.finish()
    assert isinstance(nav, BinexMessage) and binex_ephemeris_type(nav) is kind
    assert isinstance(obs, BinexMessage) and binex_epoch(obs).satellite_count == 1
    output = BytesIO()
    assert write_binex((nav, obs), output, drop_zero_prn=True) == 2
    assert output.getvalue() == wire
    assert kind.output().text == f"BINEX01{kind:02X} ONCHANGED"
    assert kind.stop().text == f"UNLOG BINEX01{kind:02X}"
    with pytest.raises(ChecksumError):
        parse_binex(navigation[:-1] + bytes([navigation[-1] ^ 1]))
