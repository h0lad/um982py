"""Check extraction of satellite ECEF states from DSP memory tables."""

from struct import pack_into

from um982py.experimental import (
    DSP_SATELLITE_STATE_FILES,
    extract_dsp_satellite_positions,
)


def test_extract_satellite_positions_from_each_constellation_table() -> None:
    lengths = {
        "gps_state": 32 * 0x78,
        "galileo_state": 36 * 0x78,
        "beidou_state": 63 * 0x78,
        "glonass_state": 24 * 0x78,
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


def test_missing_satellite_state_windows_return_no_positions() -> None:
    assert extract_dsp_satellite_positions({}) == ()
