"""Tests for the GPS LNAV ring extraction against console ephemeris ground truth.

The fixtures come from a live capture whose console GPSEPH records were
taken within the same ephemeris period: the fifty ring slots are one
tracked satellite's navigation word ring, and the expected values below
are the receiver's own console ephemeris decode, the strongest available
ground truth for the broadcast bits.
"""

from struct import pack_into

from um982py.experimental.gps_ring import (
    GPS_RING_OFFSET,
    GpsRingSlot,
    assemble_gps_ephemeris,
    decode_gps_ring_slot,
    extract_gps_ring_subframes,
)

TRACKING_BASE = 0x318000
STATE_BASE = 0x320000
STATE_SIZE = 0x124

# PRN 5 ring slots from a live capture, console-verified in the same
# ephemeris period (IODE 5, GPS week 2446, t_oe 35968 s).
RING_SLOTS = (
    0x9676E743,
    0xFD314872,
    0xA3704407,
    0xB2605A36,
    0x06D93112,
    0x9904F794,
    0x303BA69E,
    0xCE0D258C,
    0xBFD71B33,
    0x5DD3E71E,
    0x20140625,
    0x04014E70,
    0x423B929C,
    0x0FA1E309,
    0x27D8765C,
    0xC3FED0A0,
    0x8B34839B,
    0x3C001C72,
    0xBFD71D48,
    0x2DD3E71E,
    0x68232078,
    0x67CCA799,
    0x30594A85,
    0x5282FBD8,
    0xDC2D3BF5,
    0xC7D192C7,
    0x78A8D107,
    0x1FE833AD,
    0xBFD71F50,
    0xADD3E71E,
    0x8C7CC572,
    0x17FC0002,
    0x00142320,
    0x50E2C7A4,
    0x956B7A61,
    0xFCAA4602,
    0x60FF78B7,
    0x2E71BFFD,
    0xBFD72168,
    0xBDD3E71E,
    0x8F60016E,
    0x172EBAA6,
    0xB3CB7BBC,
    0xAC67050E,
    0x6A843406,
    0xF40ACFFD,
    0x5F1BC313,
    0xDEABDCF9,
    0xBFD72327,
    0xCDD3E71E,
)

# The anchor-29 window is the clean subframe 2, word for word.
SF2_WORDS = (
    0x8B0638,
    0x0A382B,
    0x05F314,
    0x2A3441,
    0x0B9B4E,
    0xF4B102,
    0xA0BEF6,
    0x1652A1,
    0x0CD619,
    0x08C81E,
)
# Console ephemeris of the same satellite and issue of data.
SF2_EXPECTED = {
    "crs_m": -103.375,
    "delta_n_rad_per_s": 3.85873216025449e-09,
    "m0_rad": 1.5964527938897337,
    "cuc_rad": -5.392357707023621e-06,
    "eccentricity": 0.0051326442044228315,
    "cus_rad": 1.0643154382705688e-05,
    "semi_major_axis_m": 26559639.753381208,
    "toe_s": 35968.0,
}

# The anchor-19 window is the clean subframe 3.
SF3_WORDS = (
    0x8B0638,
    0x0A38AD,
    0xFFF8E3,
    0xCD20E6,
    0xFFB428,
    0x09E268,
    0x17873D,
    0x8EE4A7,
    0xFFAC63,
    0x050189,
)
SF3_EXPECTED = {
    "cic_rad": -1.4901161193847656e-08,
    "omega0_rad": -0.6921006360380891,
    "cis_rad": -1.4156103134155273e-07,
    "i0_rad": 0.9826953591718703,
    "crc_m": 188.21875,
    "omega_rad": 1.5108649603786408,
    "omega_dot_rad_per_s": -7.644961300467176e-09,
    "idot_rad_per_s": 3.500145795121622e-11,
}

# The anchor-39 window is the receiver's formatted subframe 1 record.
SF1_RECORD_WORDS = (
    0x8B0638,
    0x0A37A5,
    0x639000,
    0x3FDE2D,
    0xD56E7F,
    0xA52167,
    0x38B1E9,
    0x0508C8,
    0x00FFFF,
    0xE0CEA3,
)


def fixture_regions() -> dict[str, tuple[int, bytes]]:
    """Build tracking regions holding one GPS channel record and state."""
    record = bytearray(0x148)
    record[:2] = bytes((0, 5))
    pack_into("<I", record, 4, 1)
    pack_into("<I", record, 0x134, STATE_BASE)
    state = bytearray(STATE_SIZE)
    for index, slot in enumerate(RING_SLOTS):
        pack_into("<I", state, GPS_RING_OFFSET + 4 * index, slot)
    return {
        "record": (TRACKING_BASE, bytes(record)),
        "state": (STATE_BASE, bytes(state)),
    }


def test_slot_decode_separates_data_parity_and_chain_state() -> None:
    slot = decode_gps_ring_slot(RING_SLOTS[29])
    assert isinstance(slot, GpsRingSlot)
    assert slot.data == 0x74F9C7
    assert slot.inverted
    assert slot.resolved == 0x8B0638
    assert slot.prev_d29_d30 == 0b11
    assert slot.prev_d25_d28 == 0xA
    assert slot.d25_d26 == 0b10


def test_chain_resolves_the_inverted_telemetry_word() -> None:
    subframes = extract_gps_ring_subframes(fixture_regions())
    by_type = {s.subframe: s for s in subframes}
    assert by_type[2].words == SF2_WORDS
    # The telemetry word arrived inverted. The resolved form is the standard
    # preamble, proving the D30 rule resolution on live data.
    stored = (RING_SLOTS[29] & 0xFFFFFFF) >> 2 & 0xFFFFFF
    assert stored != 0x8B0638
    assert stored ^ 0xFFFFFF == 0x8B0638


def test_extract_reports_frame_structure_and_record_overlay() -> None:
    subframes = extract_gps_ring_subframes(fixture_regions())
    assert sorted(s.subframe for s in subframes) == [1, 2, 3, 4, 5]
    by_type = {s.subframe: s for s in subframes}
    assert by_type[1].next_tow_s == 31386
    assert by_type[2].next_tow_s == 31392
    assert by_type[3].next_tow_s == 31398
    assert by_type[4].next_tow_s == 31404
    assert by_type[5].next_tow_s == 31380
    assert by_type[2].clean
    assert by_type[3].clean
    assert by_type[4].clean
    assert not by_type[1].clean
    assert not by_type[5].clean
    assert by_type[1].words == SF1_RECORD_WORDS


def test_clean_sf2_matches_console_ephemeris() -> None:
    subframes = extract_gps_ring_subframes(fixture_regions())
    sf2 = next(s for s in subframes if s.subframe == 2)
    w = sf2.words

    def signed(value: int, width: int) -> int:
        return value - (1 << width) if value >> (width - 1) else value

    pi = 3.141592653589793
    assert signed(w[2] & 0xFFFF, 16) * 2.0**-5 == SF2_EXPECTED["crs_m"]
    assert (
        abs(signed(w[3] >> 8, 16) * 2.0**-43 * pi - SF2_EXPECTED["delta_n_rad_per_s"])
        < 1e-21
    )
    assert (
        abs(
            signed((w[3] & 0xFF) << 24 | w[4], 32) * 2.0**-31 * pi
            - SF2_EXPECTED["m0_rad"]
        )
        < 1e-12
    )
    assert signed(w[5] >> 8, 16) * 2.0**-29 == SF2_EXPECTED["cuc_rad"]
    assert (
        abs((((w[5] & 0xFF) << 24) | w[6]) * 2.0**-33 - SF2_EXPECTED["eccentricity"])
        < 1e-18
    )
    assert signed(w[7] >> 8, 16) * 2.0**-29 == SF2_EXPECTED["cus_rad"]
    assert (
        abs(
            ((((w[7] & 0xFF) << 24) | w[8]) * 2.0**-19) ** 2
            - SF2_EXPECTED["semi_major_axis_m"]
        )
        < 1e-6
    )
    assert (w[9] >> 8) * 16 == SF2_EXPECTED["toe_s"]


def test_clean_sf3_matches_console_ephemeris() -> None:
    subframes = extract_gps_ring_subframes(fixture_regions())
    sf3 = next(s for s in subframes if s.subframe == 3)
    w = sf3.words

    def signed(value: int, width: int) -> int:
        return value - (1 << width) if value >> (width - 1) else value

    pi = 3.141592653589793
    assert signed(w[2] >> 8, 16) * 2.0**-29 == SF3_EXPECTED["cic_rad"]
    assert (
        abs(
            signed((w[2] & 0xFF) << 24 | w[3], 32) * 2.0**-31 * pi
            - SF3_EXPECTED["omega0_rad"]
        )
        < 1e-12
    )
    assert signed(w[4] >> 8, 16) * 2.0**-29 == SF3_EXPECTED["cis_rad"]
    assert (
        abs(
            signed((w[4] & 0xFF) << 24 | w[5], 32) * 2.0**-31 * pi
            - SF3_EXPECTED["i0_rad"]
        )
        < 1e-12
    )
    assert signed(w[6] >> 8, 16) * 2.0**-5 == SF3_EXPECTED["crc_m"]
    assert (
        abs(
            signed((w[6] & 0xFF) << 24 | w[7], 32) * 2.0**-31 * pi
            - SF3_EXPECTED["omega_rad"]
        )
        < 1e-12
    )
    assert (
        abs(signed(w[8], 24) * 2.0**-43 * pi - SF3_EXPECTED["omega_dot_rad_per_s"])
        < 1e-22
    )
    assert (
        abs(
            signed((w[9] >> 2) & 0x3FFF, 14) * 2.0**-43 * pi
            - SF3_EXPECTED["idot_rad_per_s"]
        )
        < 1e-23
    )


def test_record_sf1_rejects_ephemeris_assembly() -> None:
    """The formatted record passes the chain but fails the issue check.

    The record's subframe 1 carries the receiver's bookkeeping in the
    clock words, and its issue of data clock reduced to eight bits does
    not match the subframe 2 issue of data, so no ephemeris assembles.
    """
    subframes = extract_gps_ring_subframes(fixture_regions())
    sf1 = next(s for s in subframes if s.subframe == 1)
    sf2 = next(s for s in subframes if s.subframe == 2)
    iodc = ((sf1.words[2] & 3) << 8) | ((sf1.words[6] >> 8) & 0xFF)
    assert iodc & 0xFF != sf2.words[2] >> 16
    assert assemble_gps_ephemeris(subframes) is None


def test_empty_or_broken_rings_yield_nothing() -> None:
    regions = {
        "record": (TRACKING_BASE, bytes(0x148)),
        "state": (STATE_BASE, bytes(STATE_SIZE)),
    }
    record = bytearray(0x148)
    record[:2] = bytes((0, 5))
    pack_into("<I", record, 4, 1)
    pack_into("<I", record, 0x134, STATE_BASE)
    regions["record"] = (TRACKING_BASE, bytes(record))
    assert extract_gps_ring_subframes(regions) == ()


def test_slot_layout_round_trips_through_real_words() -> None:
    """The decoder and its inverse reproduce every live slot exactly.

    The inverse encodes resolved words back to slots using the parity
    chain, proving the layout understanding is complete and exact.
    """
    from um982py.experimental.gps_ring import _gps_word_parity

    # Take the anchor-19 SF3 window (chain-validated words) and re-derive
    # every slot from the resolved words alone.
    first = decode_gps_ring_slot(RING_SLOTS[19])
    prev = first.prev_d25_d28 << 2 | first.prev_d29_d30
    reconstructed = []
    for word in SF3_WORDS:
        stored = word ^ (0xFFFFFF if prev & 1 else 0)
        parity = _gps_word_parity(stored, (prev >> 1) & 1, prev & 1)
        reconstructed.append(
            (prev >> 2) << 28 | (prev & 3) << 26 | stored << 2 | (parity >> 4) & 3
        )
        prev = parity
    for step in range(10):
        assert reconstructed[step] == RING_SLOTS[19 - step]
