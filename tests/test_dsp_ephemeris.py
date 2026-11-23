"""Check extraction of broadcast ephemerides retained in DSP RAM."""

import math
from struct import pack_into

from um982py.experimental import (
    DspGalileoEphemeris,
    DspGlonassEphemeris,
    extract_dsp_ephemerides,
    extract_dsp_glonass_work,
)


def test_kepler_ephemeris_fields() -> None:
    data = bytearray(0xC0)
    pack_into("<H", data, 0x02, 2446)
    pack_into("<I", data, 0x08, 158400)
    pack_into("<H", data, 0xB8, 187)
    pack_into("<d", data, 0x10, math.sqrt(26_560_032.0))
    for offset, value in zip(
        range(0x18, 0x88, 8),
        (
            4e-9,
            0.1,
            0.01,
            0.2,
            1e-7,
            2e-7,
            100.0,
            -3.0,
            3e-8,
            -4e-8,
            1.0,
            5e-10,
            0.5,
            -7e-9,
        ),
        strict=True,
    ):
        pack_into("<d", data, offset, value)
    pack_into("<I", data, 0x90, 158400)
    for offset, value in ((0x98, 1e-5), (0xA0, 2e-12), (0xA8, 0.0), (0xB0, 3e-9)):
        pack_into("<d", data, offset, value)

    entries = extract_dsp_ephemerides({"gps_ephemeris": bytes(data)})
    assert len(entries) == 1
    entry = entries[0]
    assert entry.constellation == "GPS"
    assert entry.satellite_id == 1
    assert entry.toe_s == 158400
    assert entry.sqrt_a == math.sqrt(26_560_032.0)
    assert entry.mean_anomaly == 0.1
    assert entry.ascending_node_rate == -7e-9
    assert entry.af0 == 1e-5
    assert entry.group_delay_s == 3e-9
    assert entry.week_native == 2446
    assert entry.gps_week == 2446
    assert entry.iodc == 187
    assert entry.iode == 187


def test_galileo_keeps_both_clock_sets() -> None:
    data = bytearray(0xF0)
    pack_into("<H", data, 0x02, 1422)
    data[0x04] = 13
    pack_into("<I", data, 0x10, 152400)
    pack_into("<d", data, 0x18, 5440.5)
    pack_into("<I", data, 0x98, 152400)
    pack_into("<I", data, 0xB8, 151800)
    for offset, value in (
        (0xA0, 0.001),
        (0xA8, 1e-11),
        (0xB0, 0.0),
        (0xC0, 0.002),
        (0xC8, 2e-11),
        (0xD0, 0.0),
        (0xD8, 3e-9),
        (0xE0, 4e-9),
    ):
        pack_into("<d", data, offset, value)

    entries = extract_dsp_ephemerides({"galileo_ephemeris": bytes(data)})
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, DspGalileoEphemeris)
    assert entry.inav_toc_s == 152400
    assert entry.inav_af0 == 0.001
    assert entry.fnav_toc_s == 151800
    assert entry.fnav_af0 == 0.002
    assert (entry.e1e5a_bgd_s, entry.e1e5b_bgd_s) == (3e-9, 4e-9)
    assert entry.week_native == 1422
    assert entry.gps_week == 2446
    assert entry.iodnav == 13


def test_beidou_issue_fields() -> None:
    data = bytearray(0xC0)
    pack_into("<H", data, 0x02, 1090)
    pack_into("<I", data, 0x08, 158400)
    pack_into("<d", data, 0x10, math.sqrt(42_159_016.0))
    data[0x06] = 1
    data[0x07] = 1

    entries = extract_dsp_ephemerides({"beidou_ephemeris": bytes(data)})
    assert len(entries) == 1
    entry = entries[0]
    assert entry.constellation == "BEIDOU"
    assert entry.week_native == 1090
    assert entry.gps_week == 2446
    assert (entry.aode, entry.aode_2) == (1, 1)


def test_glonass_state_vector() -> None:
    data = bytearray(0x78)
    for offset in range(0x08, 0x68, 8):
        pack_into("<d", data, offset, 0.0)
    for offset, value in (
        (0x20, 20_000_000.0),
        (0x28, 10_000_000.0),
        (0x30, 10_000_000.0),
    ):
        pack_into("<d", data, offset, value)
    data[0x02] = 9
    data[0x04] = 5
    pack_into("<I", data, 0x68, 81900)
    pack_into("<H", data, 0x70, 1058)

    entries = extract_dsp_ephemerides({"glonass_ephemeris": bytes(data)})
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, DspGlonassEphemeris)
    assert entry.satellite_id == 38
    assert entry.e_time_sod_s == 81900
    assert (entry.x, entry.y, entry.z) == (20_000_000.0, 10_000_000.0, 10_000_000.0)
    assert entry.nt == 1058
    assert entry.ft == 5
    assert entry.flags == 9


def test_glonass_work_record() -> None:
    data = bytearray(0x40)
    pack_into("<I", data, 0, 900)
    for offset, value in zip(
        range(0x08, 0x40, 8),
        (825.0, 20_000_000.0, 10_000_000.0, 10_000_000.0, 1.0, 2.0, 3.0),
        strict=True,
    ):
        pack_into("<d", data, offset, value)

    (record,) = extract_dsp_glonass_work({"glonass_work": bytes(data)})
    assert record.index == 0
    assert record.reference_time_sod_s == 900
    assert record.propagation_time_sod_s == 825.0
    assert record.position_ecef_m == (20_000_000.0, 10_000_000.0, 10_000_000.0)
    assert record.velocity_ecef_mps == (1.0, 2.0, 3.0)


def test_missing_tables_return_no_ephemerides() -> None:
    assert extract_dsp_ephemerides({}) == ()
