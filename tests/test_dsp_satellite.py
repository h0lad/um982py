"""Check extraction of satellite ECEF states from DSP memory tables."""

from struct import pack_into

from um982py.experimental import (
    DSP_SATELLITE_STATE_FILES,
    extract_dsp_satellite_positions,
)


def test_extract_satellite_positions_from_each_constellation_table() -> None:
    lengths = {
        "gps_state": 42 * 0x78,
        "galileo_state": 36 * 0x78,
        "beidou_state": 63 * 0x78,
        "glonass_state": 32 * 0x78,
    }
    regions = {name: bytearray(lengths[name]) for name in DSP_SATELLITE_STATE_FILES}
    expected = (
        (
            "gps_state",
            0,
            (15_000_000.0, 20_000_000.0, 10_000_000.0),
            (500.0, -2_000.0, 3_000.0),
            (100_000_000, 99_999_000, "GPST"),
        ),
        (
            "galileo_state",
            35,
            (-13_500_000.0, 20_400_000.0, 17_000_000.0),
            (-1_000.0, 2_000.0, 3_000.0),
            (99_999_000, 99_998_000, "GST"),
        ),
        (
            "beidou_state",
            62,
            (42_200_000.0, 0.0, 0.0),
            (0.0, 5.0, 10.0),
            (85_986_000, 85_985_000, "BDT"),
        ),
        (
            "glonass_state",
            0,
            (10_000_000.0, 20_000_000.0, 12_000_000.0),
            (-80.0, 190.0, 3_580.0),
            (24_382_000, 24_381_000, "GLOT"),
        ),
    )
    for name, index, position, velocity, times in expected:
        data = regions[name]
        offset = index * 0x78
        pack_into("<3d", data, offset, *position)
        pack_into("<3d", data, offset + 0x18, *velocity)
        pack_into("<2I", data, offset + 0x68, *times[:2])
        pack_into("<I", data, offset + 0x74, 0x3F)

    # Empty and non-orbital entries do not become apparent satellites.
    gps = regions["gps_state"]
    pack_into("<3d", gps, 0x78, float("nan"), 0.0, 0.0)
    beidou = regions["beidou_state"]
    pack_into("<3d", beidou, 0, 20_000_000.0, 20_000_000.0, 20_000_000.0)

    positions = extract_dsp_satellite_positions(
        {name: bytes(data) for name, data in regions.items()}
    )
    by_id = {
        (position.constellation, position.satellite_id): position
        for position in positions
    }

    assert set(by_id) == {
        ("GPS", 1),
        ("GALILEO", 36),
        ("BEIDOU", 63),
        ("GLONASS", 65),
    }
    assert by_id[("GPS", 1)].receiver_id == 1
    assert by_id[("GPS", 1)].position_ecef_m == (
        15_000_000.0,
        20_000_000.0,
        10_000_000.0,
    )
    assert by_id[("GPS", 1)].velocity_ecef_mps == (500.0, -2_000.0, 3_000.0)
    assert by_id[("GPS", 1)].state_flags == 0x3F
    assert by_id[("GPS", 1)].state_time_ms == 100_000_000
    assert by_id[("GPS", 1)].secondary_time_ms == 99_999_000
    assert by_id[("GPS", 1)].time_scale == "GPST"
    assert by_id[("GALILEO", 36)].receiver_id == 136
    assert by_id[("GALILEO", 36)].time_scale == "GST"
    assert by_id[("BEIDOU", 63)].receiver_id == 223
    assert by_id[("BEIDOU", 63)].time_scale == "BDT"
    assert by_id[("GLONASS", 65)].time_scale == "GLOT"
    assert by_id[("GPS", 1)].radius_m > 25_000_000.0


def test_hidden_range_and_sky_fields() -> None:
    regions = {
        "gps_state": bytearray(0x78),
        "glonass_state": bytearray(0x78),
    }
    gps = regions["gps_state"]
    pack_into("<3d", gps, 0, 15_000_000.0, 20_000_000.0, 10_000_000.0)
    pack_into("<3d", gps, 0x30, 25_000_000.0, 25_000_100.0, -500.0)
    pack_into("<2f", gps, 0x60, 0.5, 1.25)
    pack_into("<I", gps, 0x70, 1234)
    pack_into("<I", gps, 0x74, 0x2F)

    glonass = regions["glonass_state"]
    pack_into("<3d", glonass, 0, 10_000_000.0, 20_000_000.0, 12_000_000.0)
    pack_into("<I", glonass, 0x74, 0x440F)

    positions = extract_dsp_satellite_positions(regions)
    gps_state, glonass_state = positions
    assert gps_state.range_m == 25_000_000.0
    assert gps_state.pseudorange_m == 25_000_100.0
    assert gps_state.approach_rate_mps == -500.0
    assert gps_state.elevation_rad == 0.5
    assert gps_state.azimuth_rad == 1.25
    assert gps_state.broadcast_ephemeris_age_s == 1234
    assert gps_state.valid
    assert gps_state.broadcast_path_selected
    assert gps_state.ionosphere_correction_selected
    assert not gps_state.diagnostic_status_bit
    assert glonass_state.range_m is None
    assert glonass_state.pseudorange_m is None
    assert glonass_state.approach_rate_mps is None
    assert glonass_state.elevation_rad == 0.0
    assert glonass_state.azimuth_rad == 0.0
    assert glonass_state.broadcast_ephemeris_age_s is None
    assert glonass_state.glonass_frequency_channel == 3
    assert glonass_state.valid
    assert glonass_state.broadcast_path_selected
    assert glonass_state.ionosphere_correction_selected
    assert not glonass_state.diagnostic_status_bit


def test_tail_records_and_short_table_prefixes() -> None:
    lengths = {
        "gps_state": 42 * 0x78,
        "glonass_state": 32 * 0x78,
    }
    regions = {name: bytearray(length) for name, length in lengths.items()}
    for name, index in (("gps_state", 41), ("glonass_state", 31)):
        offset = index * 0x78
        pack_into(
            "<3d", regions[name], offset, 15_000_000.0, 20_000_000.0, 10_000_000.0
        )
        pack_into("<2I", regions[name], offset + 0x68, 100_000_000, 100_000_000)
        pack_into("<I", regions[name], offset + 0x74, 0x3F)

    positions = extract_dsp_satellite_positions(regions)
    assert {
        (position.constellation, position.satellite_id) for position in positions
    } == {("GPS", 42), ("GLONASS", 96)}

    shorter = {name: bytes(data[: 24 * 0x78]) for name, data in regions.items()}
    assert extract_dsp_satellite_positions(shorter) == ()


def test_missing_satellite_state_windows_return_no_positions() -> None:
    assert extract_dsp_satellite_positions({}) == ()
