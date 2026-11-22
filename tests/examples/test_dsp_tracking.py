"""Ensure the DSP example uses boot memory and supports offline replay."""

import json
from pathlib import Path
from struct import pack_into
from unittest.mock import MagicMock

import pytest
from examples.dsp_tracking import __main__ as cli

from um982py.experimental import (
    DSP_RECEIVER_MEMORY_WINDOWS,
    DSP_TRACKING_MEMORY_WINDOWS,
)


def test_boot_capture_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    windows = {
        base: bytearray(length)
        for _, base, length in DSP_TRACKING_MEMORY_WINDOWS + DSP_RECEIVER_MEMORY_WINDOWS
    }
    heap = windows[0x318000]
    pack_into("<I", heap, 0x331DF8 - 0x318000, 0x318000)
    heap[:3] = bytes([3, 12, 5])
    pack_into("<h", heap, 0x0E, 3900)
    pack_into("<I", heap, 0x1C, 0x466123)
    pack_into("<i", heap, 0x30, 1200)
    heap[0x80:0x82] = bytes([3, 112])
    pack_into("<I2xH", heap, 0x84, 1, 0x11)
    pack_into("<2d", heap, 0x90, 25_488_463.1169, 133_942_786.7349)
    pack_into("<f", heap, 0xA0, 24.5)
    pack_into("<2f", heap, 0xB0, 0.25, 0.015625)
    pack_into("<d", heap, 0xC8, 133_942_787.0)
    pack_into("<I", heap, 0x144, 34010)
    pack_into("<2I", heap, 0x154, 75, 587_112_000)
    pack_into("<I", windows[0x42BCB4], 0, 0x318080)
    pack_into("<I", heap, 0x331DF8 - 0x318000 + 4, 0x318180)
    heap[0x180:0x1FE] = heap[:0x7E]
    heap[0x180] = 0x13
    heap[0x200:0x2DC] = heap[0x80:0x15C]
    heap[0x200] = 0x13
    pack_into("<I", heap, 0x204, 158)
    pack_into("<I", windows[0x42BCB4], 157 * 4, 0x318200)
    pack_into("<d", windows[0x402520], 8, 0.125)
    pack_into("<i", windows[0x402520], 0x18, 1000)
    pack_into("<8B", heap, 0x32CD7C - 0x318000, 62, 72, 74, 77, 74, 41, 57, 68)
    pack_into("<I2i", windows[0x13D42388], 0, 3, 49427, 44595)
    pack_into("<I12xI", windows[0x13D443B0], 0, 576824000, 2445)
    pack_into("<8f2B", windows[0x13D704C4], 0, *range(1, 9), 18, 1)
    notice = b"$AntStatus:1,1\r\n"
    windows[0x402C00][: len(notice)] = notice

    reader = MagicMock()
    reader.__enter__.return_value = reader
    reader.application_restored = True

    def read_range(address: int, size: int) -> bytes:
        assert len(windows[address]) == size
        return bytes(windows[address])

    reader.read_range.side_effect = read_range
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
    assert "Application restored yes" in capsys.readouterr().out
    report = json.loads(output.read_text())
    assert report["application_restored"] is True
    assert report["channels"][0]["doppler_hz"] == 25.0
    assert report["channels"][0]["cn0_dbhz"] == 39.0
    observation = report["channels"][0]["observation"]
    assert observation["gps_tow_ms"] == 587_112_000
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
    assert state["cached_notices"] == [
        {"buffer_address": 0x402C00, "name": "ANT_STATUS", "text": notice.decode()}
    ]

    (snapshot / "rf_calibration.bin").unlink()
    (snapshot / "channels.bin").write_bytes(windows[0x42BCB4][: 157 * 4])
    pack_into("<H", heap, 0x8A, 1)
    (snapshot / "tracking.bin").write_bytes(heap)
    connect.reset_mock()
    assert cli.main(["--replay", str(snapshot), "--json", str(output)]) == 0
    connect.assert_not_called()
    replay = json.loads(output.read_text())
    assert replay["application_restored"] is None
    assert replay["channels"][0]["doppler_hz"] is None
    assert replay["channels"][0]["carrier_word"] == 1200
    assert len(replay["channels"]) == 1
    assert replay["receiver_state"] == state
    observation = replay["channels"][0]["observation"]
    assert observation["carrier_phase_cycles"] is None
    assert observation["phase_offset_cycles"] is None
