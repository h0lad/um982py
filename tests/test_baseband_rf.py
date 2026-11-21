from pathlib import Path
from struct import pack

import pytest

from test_protocol import binary
from um982py.capture import iter_frames
from um982py.commands import Log
from um982py.errors import ProtocolError
from um982py.experimental import (
    AgcReadings,
    AntennaSignalProfile,
    RawBasebandPacket,
    TrackingSlot,
    build_message,
    decode_agc_message,
)
from um982py.protocol.binary import parse_binary

CAPTURES = Path(__file__).parent / "fixtures/captures"


@pytest.mark.parametrize("antenna,group", [(1, 3), (2, 6)])
def test_signal_profiles_normalize_ascii_and_binary_systems(
    antenna: int, group: int
) -> None:
    log = Log.ANT1GROUP if antenna == 1 else Log.ANT2GROUP
    first, second = (
        AntennaSignalProfile.from_record(
            log.decode(next(iter_frames(CAPTURES / f"ANT{antenna}GROUP{suffix}.bin")))
        )
        for suffix in ("A", "B")
    )
    assert (
        (first.antenna, first.group)
        == (second.antenna, second.group)
        == (antenna, group)
    )
    assert [
        (row.constellation, row.mask, row.bands, row.unknown_bits)
        for row in first.masks
    ] == [
        (row.constellation, row.mask, row.bands, row.unknown_bits)
        for row in second.masks
    ]
    assert first.masks[0].bands == (
        ("L1", "L2", "L5") if antenna == 1 else ("L1", "L2")
    )
    assert first.masks[-1].unknown_bits == first.masks[-1].mask


def test_agc_serial_conversion_matches_baseband_mapping() -> None:
    words = (8, 37, 66, 51, 15, 71, 64, 82, -1, 9)
    framed = build_message(23, bytes(range(12)) + pack("<10i", *words))
    (inner,) = RawBasebandPacket.build(content=framed).messages
    direct = decode_agc_message(inner)
    assert direct.native_words == words
    assert direct.rf_channels == (64, -1, 82, 71, 15, 37, 51, 66)
    serial = pack("<10h", 37, 66, 51, 71, -1, 64, 82, -1, -1, -1)
    record = Log.AGC.decode(parse_binary(binary(serial, message_id=220)))
    assert direct.readings(secondary_enabled=True) == AgcReadings.from_record(record)
    assert direct.readings(secondary_enabled=False) == AgcReadings(
        37, 66, 51, 71, None, None, None
    )


def test_tracking_slot_matches_native_group_fields() -> None:
    slot = TrackingSlot(16, 1, 7, False, 0.0)
    assert slot.matches_rf_group(antenna=1, signal_code=0x1B, status=0, mode=0)
    assert slot.matches_rf_group(antenna=1, signal_code=0x1A, status=0x400, mode=13)
    assert not slot.matches_rf_group(antenna=1, signal_code=0x1A, status=0, mode=13)
    assert not slot.matches_rf_group(antenna=0, signal_code=0x1B, status=0, mode=0)


@pytest.mark.parametrize("message_id,error", [(23, "needs 52"), (24, "message 23")])
def test_agc_inner_frame_validates_id_and_length(message_id: int, error: str) -> None:
    (message,) = RawBasebandPacket.build(
        content=build_message(message_id, b"x")
    ).messages
    with pytest.raises(ProtocolError, match=error):
        decode_agc_message(message)
