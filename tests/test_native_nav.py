"""Tests for the native tracking-window GPS and GLONASS layouts."""

from struct import pack_into

from um982py.experimental import extract_native_nav

TRACKING_BASE = 0x318000
STATE_BASE = 0x320000
GPS_STATE_OFFSET = 0
GLONASS_STATE_OFFSET = 0x140

# Observed navigation bytes, stored in the receiver's native order.
GPS_BUFFER = bytes.fromhex(
    "b806e64cfd01000040675ce8a7432e2e408c8b99cada114305a040ec0300d418fc540a510d8dc122"
)
GLONASS_BUFFER = bytes.fromhex("7d2910260200a05c25811400")


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
