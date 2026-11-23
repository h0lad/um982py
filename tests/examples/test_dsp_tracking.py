"""Ensure the DSP example uses boot memory and supports offline replay."""

import json
from pathlib import Path
from struct import pack_into
from unittest.mock import MagicMock

import pytest
from examples.dsp_tracking import __main__ as cli

from um982py.experimental import (
    DSP_EPHEMERIS_MEMORY_WINDOWS,
    DSP_RECEIVER_MEMORY_WINDOWS,
    DSP_SATELLITE_STATE_FILES,
    DSP_TRACKING_CLOCK_REFERENCE_WINDOW,
    DSP_TRACKING_MEMORY_WINDOWS,
)


def test_boot_capture_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    windows = {
        base: bytearray(length)
        for _, base, length in (
            *DSP_TRACKING_MEMORY_WINDOWS,
            *DSP_RECEIVER_MEMORY_WINDOWS,
            DSP_TRACKING_CLOCK_REFERENCE_WINDOW,
            *DSP_EPHEMERIS_MEMORY_WINDOWS,
        )
    }
    satellite_lengths = {
        "gps_state": 42 * 0x78,
        "galileo_state": 36 * 0x78,
        "beidou_state": 63 * 0x78,
        "glonass_state": 32 * 0x78,
    }
    satellite_state = {
        name: bytearray(satellite_lengths[name]) for name in DSP_SATELLITE_STATE_FILES
    }
    tracking_window = windows[0x318000]
    pack_into("<I", tracking_window, 0x331DF8 - 0x318000, 0x318000)
    tracking_window[:3] = bytes([3, 12, 5])
    pack_into("<h", tracking_window, 0x0E, 3900)
    pack_into("<I", tracking_window, 0x1C, 0x466123)
    pack_into("<i", tracking_window, 0x30, 1200)
    tracking_window[0x80:0x82] = bytes([3, 112])
    pack_into("<I2xH", tracking_window, 0x84, 1, 0x11)
    pack_into("<2d", tracking_window, 0x90, 25_488_463.1169, 133_942_786.7349)
    pack_into("<d", tracking_window, 0x108, 587_111.925)
    pack_into("<f", tracking_window, 0x110, 12.5)
    pack_into("<f", tracking_window, 0xA0, 24.5)
    pack_into("<2f", tracking_window, 0xB0, 0.25, 0.015625)
    pack_into("<d", tracking_window, 0xC8, 133_942_787.0)
    pack_into("<I", tracking_window, 0x144, 34010)
    pack_into("<2I", tracking_window, 0x154, 75, 587_112_000)
    pack_into("<I", windows[0x42BCB4], 0, 0x318080)
    pack_into("<I", tracking_window, 0x331DF8 - 0x318000 + 4, 0x318180)
    tracking_window[0x180:0x1FE] = tracking_window[:0x7E]
    tracking_window[0x180] = 0x13
    tracking_window[0x200:0x2DC] = tracking_window[0x80:0x15C]
    tracking_window[0x200] = 0x13
    pack_into("<I", tracking_window, 0x204, 158)
    pack_into("<I", windows[0x42BCB4], 157 * 4, 0x318200)
    pack_into("<d", windows[0x402520], 8, 0.125)
    pack_into("<i", windows[0x402520], 0x18, 1000)
    pack_into(
        "<8B", tracking_window, 0x32CD7C - 0x318000, 62, 72, 74, 77, 74, 41, 57, 68
    )
    pack_into("<I2i", windows[0x13D42388], 0, 3, 49427, 44595)
    pack_into(
        "<3d", satellite_state["gps_state"], 0, 15_000_000, 20_000_000, 10_000_000
    )
    pack_into("<3d", satellite_state["gps_state"], 0x18, 500, -2000, 3000)
    pack_into(
        "<3d", satellite_state["gps_state"], 0x30, 25_488_463.0, 25_488_563.0, -123.5
    )
    pack_into("<2f", satellite_state["gps_state"], 0x60, 0.25, 1.5)
    pack_into("<I", satellite_state["gps_state"], 0x70, 4321)
    pack_into("<2I", satellite_state["gps_state"], 0x68, 587_112_000, 587_111_000)
    pack_into("<I", satellite_state["gps_state"], 0x74, 0x3F)
    pack_into("<I12xI", windows[0x13D443B0], 0, 576824000, 2445)
    pack_into("<8f2B", windows[0x13D704C4], 0, *range(1, 9), 18, 1)
    notice = b"$AntStatus:1,1\r\n"
    windows[0x402C00][: len(notice)] = notice
    pack_into("<d", windows[0x13D442E0], 8, 2.5)
    gps_eph = windows[0x13D729E8]
    pack_into("<H", gps_eph, 2, 2446)
    pack_into("<I", gps_eph, 8, 158400)
    pack_into("<d", gps_eph, 0x10, 5153.0)
    pack_into("<H", gps_eph, 0xB8, 187)
    work = windows[0x13D02600]
    pack_into("<I", work, 0, 900)
    pack_into("<d", work, 8, 825.0)
    pack_into("<3d", work, 0x10, 20_000_000.0, 10_000_000.0, 10_000_000.0)
    pack_into("<3d", work, 0x28, 1.0, 2.0, 3.0)

    reader = MagicMock()
    reader.__enter__.return_value = reader
    reader.application_restored = True

    def read_range(address: int, size: int) -> bytes:
        assert len(windows[address]) == size
        return bytes(windows[address])

    reader.read_range.side_effect = read_range
    monkeypatch.setattr(
        cli,
        "read_dsp_satellite_state_windows",
        lambda _: {name: bytes(data) for name, data in satellite_state.items()},
    )
    connect = MagicMock(return_value=reader)
    monkeypatch.setattr(cli.BootMemoryReader, "connect", connect)
    snapshot = tmp_path / "snapshot"
    output = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "--port",
                "serial",
                "--boot-menu",
                "--receiver-state",
                "--satellite-states",
                "--save-ram",
                str(snapshot),
                "--json",
                str(output),
            ]
        )
        == 0
    )
    connect.assert_called_once_with(
        "serial",
        921600,
        helper=cli.DEFAULT_READER,
        boot_menu_only=True,
    )
    reader.__exit__.assert_called_once()
    console = capsys.readouterr().out
    assert "restored=yes" in console
    assert "587111.925" in console and "GST" in console
    assert "SAT n=1" in console
    assert "DETAIL" in console and "CHX n=2" in console
    assert "OBS ch=1" in console
    assert "clock_correction_s=10.0" in console
    assert "EPH n=1" in console and "iodc=187" in console
    assert "GLOPROP n=1" in console and "reference_time_sod_s=900" in console
    report = json.loads(output.read_text())
    assert report["application_restored"] is True
    assert report["satellite_positions"] == [
        {
            "constellation": "GPS",
            "satellite_id": 1,
            "receiver_id": 1,
            "position_ecef_m": [15_000_000.0, 20_000_000.0, 10_000_000.0],
            "velocity_ecef_mps": [500.0, -2000.0, 3000.0],
            "range_m": 25_488_463.0,
            "pseudorange_m": 25_488_563.0,
            "approach_rate_mps": -123.5,
            "elevation_rad": 0.25,
            "azimuth_rad": 1.5,
            "broadcast_ephemeris_age_s": 4321,
            "state_flags": 63,
            "glonass_frequency_channel": None,
            "state_time_ms": 587112000,
            "secondary_time_ms": 587111000,
            "time_scale": "GPST",
        }
    ]
    assert "address" not in report["channels"][0]
    assert "address" not in report["channels"][0]["observation"]
    assert report["channels"][0]["doppler_hz"] == 25.0
    assert report["channels"][0]["cn0_dbhz"] == 39.0
    observation = report["channels"][0]["observation"]
    assert observation["gps_tow_ms"] == 587_112_000
    assert observation["native_time_s"] == pytest.approx(587_111.925)
    assert observation["native_time_scale"] == "GST"
    assert observation["epoch_counter"] == 75
    assert observation["pseudorange_m"] == 25_488_463.1169
    assert observation["phase_offset_cycles"] == pytest.approx(-0.2651)
    assert observation["doppler_hz"] == 24.5
    assert observation["pseudorange_std_m"] == 0.25
    assert observation["carrier_phase_std_cycles"] == 0.015625
    assert observation["phase_lock_ms"] == 34010
    assert report["channels"][0]["band"] == "E1"
    assert len(report["channels"]) == 2
    assert report["channels"][1]["channel"] == 158
    assert report["channels"][1]["band"] == "E5a"
    assert report["channels"][1]["satellite_id"] == 12
    assert report["channels"][1]["frequency_hz"] == 1176.45e6
    state = report["receiver_state"]
    assert state["gps_epoch"] == {"week": 2445, "tow_ms": 576824000}
    assert state["rf_agc_codes"] == [62, 72, 74, 77, 74, 41, 57, 68]
    assert state["sensor_adc"] == {"channel": 3, "value_1": 49427, "value_2": 44595}
    assert state["gps_ionosphere"]["beta"] == [5.0, 6.0, 7.0, 8.0]
    assert state["gps_ionosphere"]["flags"] == [1, 18]
    assert state["cached_notices"] == [{"name": "ANT_STATUS", "text": notice.decode()}]
    assert report["broadcast_ephemerides"][0]["iodc"] == 187
    assert report["glonass_propagation"][0]["reference_time_sod_s"] == 900

    (snapshot / "rf_calibration.bin").unlink()
    (snapshot / "channels.bin").write_bytes(windows[0x42BCB4][: 157 * 4])
    pack_into("<H", tracking_window, 0x8A, 1)
    (snapshot / "tracking.bin").write_bytes(tracking_window)
    connect.reset_mock()
    assert cli.main(["--replay", str(snapshot), "--json", str(output)]) == 0
    connect.assert_not_called()
    replay = json.loads(output.read_text())
    assert replay["application_restored"] is None
    assert replay["channels"][0]["doppler_hz"] is None
    assert replay["channels"][0]["carrier_word"] == 1200
    assert len(replay["channels"]) == 1
    assert replay["receiver_state"] == state
    assert replay["broadcast_ephemerides"] == report["broadcast_ephemerides"]
    assert replay["glonass_propagation"] == report["glonass_propagation"]
    assert replay["satellite_positions"] == report["satellite_positions"]
    observation = replay["channels"][0]["observation"]
    assert observation["carrier_phase_cycles"] is None
    assert observation["phase_offset_cycles"] is None
