"""Tests for the native tracking-window GPS and GLONASS layouts."""

from struct import pack_into

import pytest

from um982py.experimental import extract_beidou_nav, extract_native_nav

TRACKING_BASE = 0x318000
STATE_BASE = 0x320000
GPS_STATE_OFFSET = 0
GLONASS_STATE_OFFSET = 0x140

# Observed navigation bytes, stored in the receiver's native order.
GPS_BUFFER = bytes.fromhex(
    "b806e64cfd01000040675ce8a7432e2e408c8b99cada114305a040ec0300d418fc540a510d8dc122"
)
GLONASS_BUFFER = bytes.fromhex("7d2910260200a05c25811400")
BEIDOU_BUFFER = bytes.fromhex(
    "207178d24317e0ed6ff8216ba96ad1a2f28a2c4405d9e4b8feab0305840df26689053699"
    "ba117f1c20710f27"
)


def _regions(*, corrupt: bool = False) -> dict[str, tuple[int, bytes]]:
    records = bytearray(0x298)
    state = bytearray(0x200)
    for offset, family, svid, channel, state_offset in (
        (0, 0, 26, 1, GPS_STATE_OFFSET),
        (0x150, 0x34, 65, 34, GLONASS_STATE_OFFSET),
    ):
        records[offset : offset + 2] = bytes((family, svid))
        pack_into("<I", records, offset + 4, channel)
        pack_into("<I", records, offset + 0x134, STATE_BASE + state_offset)
    state[0xF4:0x11C] = GPS_BUFFER
    glonass_position = GLONASS_STATE_OFFSET + 0x4C
    state[glonass_position : glonass_position + 12] = GLONASS_BUFFER
    if corrupt:
        state[0xF4] ^= 1
        state[glonass_position] ^= 1
    return {
        "records": (TRACKING_BASE, bytes(records)),
        "state": (STATE_BASE, bytes(state)),
    }


def test_extracts_raw_gps_lnav_and_glonass_fdma() -> None:
    gps, glonass = extract_native_nav(_regions())
    (subframe,) = gps
    assert (subframe.prn, subframe.channel) == (26, 1)
    assert (subframe.subframe, subframe.next_subframe_tow_s) == (3, 577038)
    assert len(subframe.words) == 10
    assert subframe.words[0] == 0x22C18D0D
    assert subframe.data_words[:2] == (0x8B0634, 0xBBD6AC)

    (string,) = glonass
    assert (string.receiver_svid, string.channel, string.string_number) == (65, 34, 11)
    assert string.manifest()["hex"] == "0b7edaa35ffffdd9efd682"


def test_rejects_corrupted_words_and_strings() -> None:
    assert extract_native_nav(_regions(corrupt=True)) == ((), ())


@pytest.mark.parametrize("corrupt", [False, True])
def test_extract_beidou_subframe_from_unaligned_hardware_buffer(corrupt: bool) -> None:
    record = bytearray(0x148)
    record[:2] = bytes((0x22, 201))
    pack_into("<I", record, 4, 64)
    pack_into("<I", record, 0x134, STATE_BASE)
    state = bytearray(0x1AC)
    state[0x50:0x7C] = BEIDOU_BUFFER
    if corrupt:
        state[0x54] ^= 1
    result = extract_beidou_nav({
        "record": (TRACKING_BASE, bytes(record)),
        "state": (STATE_BASE, bytes(state)),
    })
    if corrupt:
        assert result == ()
    else:
        (frame,) = result
        assert (frame.receiver_svid, frame.channel, frame.subframe, frame.sow_s) == (
            201, 64, 3, 587082,
        )
        raw = "".join(f"{word:030b}" for word in frame.words)
        assert f"{int(raw, 2):075x}" == (
            "e240e3f88dd326c0b1337906c20a0757fdc726c82885915e5168b554d643f0df6f00ba1a4f0"
        )
