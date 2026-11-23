"""Check DSP address resolution, raw fields and calibrated Doppler."""

from struct import pack, pack_into

import pytest

from um982py.experimental import extract_dsp_tracking


@pytest.mark.parametrize(
    ("family", "svid", "bias", "offset_hz"),
    [(0x03, 12, 100, 0), (0x34, 9, 64, -562500), (0x3C, 7, 64, 437500)],
)
def test_extract_dsp_tracking(
    family: int,
    svid: int,
    bias: int,
    offset_hz: int,
) -> None:
    row = bytearray(0x7E)
    row[:3] = bytes([family, svid, 5])
    row[9] = 2
    pack_into("<h", row, 0x0E, 3850)
    pack_into("<H", row, 0x12, 4)
    pack_into("<I", row, 0x1C, 0x466123)
    pack_into("<4Ii2I", row, 0x20, 2, 8, 0x80000000, 9, -(2**31) + 5, 10, 11)
    tracker = bytearray(12)
    tracker[:2] = bytes([family, svid + bias])
    pack_into("<I2xH", tracker, 4, 2, 1)
    links = bytearray(0x20)
    pack_into("<I", links, 0x1C, 0x3A0000)
    channel_links = bytearray(8)
    pack_into("<I", channel_links, 4, 0x3B0000)
    rf = bytearray(0x1C)
    pack_into("<d", rf, 8, 0.25)
    pack_into("<i", rf, 0x18, 2**31 - 3)
    windows = {
        "measurements": (0x331DF8, bytes(links)),
        "channels": (0x42BCB4, bytes(channel_links)),
        "row": (0x3A0000, bytes(row)),
        "tracker": (0x3B0000, bytes(tracker)),
        "rf": (0x4025C0, bytes(rf)),
    }
    (record,) = extract_dsp_tracking(windows)
    assert record.channel == 2
    assert (record.signal_family, record.svid) == (family, svid)
    assert record.address == 0x3A0000
    assert record.raw == row
    assert record.observation is None
    assert record.cn0_dbhz == 38.5
    assert record.tracking_status == 0x466123
    assert record.carrier_word == -(2**31) + 5
    assert record.doppler_hz == 2 + offset_hz
    assert record.calibration is not None
    assert record.calibration.reference_word == 2**31 - 3
    assert record.calibration.effective_sample_clock_hz == 0.25 * 2**32
    assert record.diagnostic_words == (9, 10, 11, 2, 8, 0x80000000)
    assert record.normalized_accumulator == 51150

    windows["rf"] = (0x4025C0, bytes(len(rf)))
    (record,) = extract_dsp_tracking(windows)
    assert record.doppler_hz is None

    windows["tracker"] = (0x3B0000, bytes(tracker[:10]) + b"\x00\x00")
    assert extract_dsp_tracking(windows) == ()


def test_output_clock_correction() -> None:
    row = bytearray(0x7E)
    row[:3] = bytes([0, 22, 5])
    pack_into("<I", row, 0x1C, 0x466123)
    measurement_links = bytearray(4)
    pack_into("<I", measurement_links, 0, 0x3A0000)
    channel_links = bytearray(4)
    pack_into("<I", channel_links, 0, 0x3B0000)
    tracker = bytearray(0xDC)
    tracker[:2] = bytes([0, 22])
    pack_into("<I2xH", tracker, 4, 1, 0x11)
    pack_into("<2d", tracker, 0x10, 21_000_000.0, 110_000_000.0)
    pack_into("<f", tracker, 0x90, 12.5)
    pack_into("<2I", tracker, 0xD4, 1, 100_000_000)
    windows = {
        "measurements": (0x331DF8, bytes(measurement_links)),
        "channels": (0x42BCB4, bytes(channel_links)),
        "row": (0x3A0000, bytes(row)),
        "tracker": (0x3B0000, bytes(tracker)),
        "clock_reference": (0x13D442E0, b"\x00" * 8 + pack("<d", 2.5)),
    }

    (record,) = extract_dsp_tracking(windows)
    assert record.observation is not None
    assert record.observation.clock_correction_s == 10.0
    assert record.observation.range_correction_m == 80.0


@pytest.mark.parametrize(
    ("family", "svid", "bias", "native_time", "time_scale"),
    [
        (0x00, 22, 0, 99_999.925, "GPST"),
        (0x03, 12, 100, 99_999.925, "GST"),
        (0x12, 6, 160, 85_985.925, "BDT"),
        (0x34, 9, 64, 24_381.925, "GLOT"),
        (0x00, 22, 0, float("nan"), None),
        (0x34, 9, 64, 86_400.0, None),
    ],
)
def test_extract_native_observation_time(
    family: int,
    svid: int,
    bias: int,
    native_time: float,
    time_scale: str | None,
) -> None:
    row = bytearray(0x7E)
    row[:3] = bytes([family, svid, 5])
    row[9] = 2
    pack_into("<I", row, 0x1C, 0x466123)
    measurement_links = bytearray(4)
    pack_into("<I", measurement_links, 0, 0x3A0000)
    channel_links = bytearray(4)
    pack_into("<I", channel_links, 0, 0x3B0000)
    tracker = bytearray(0xDC)
    tracker[:2] = bytes([family, svid + bias])
    if family in (0x34, 0x3C):
        pack_into("<H", tracker, 2, 73)
    pack_into("<I2xH", tracker, 4, 1, 0x11)
    pack_into("<2d", tracker, 0x10, 21_000_000.0, 110_000_000.0)
    pack_into("<f", tracker, 0x20, -1200.0)
    pack_into("<2f", tracker, 0x30, 0.5, 0.02)
    pack_into("<d", tracker, 0x48, 110_000_000.0)
    pack_into("<d", tracker, 0x88, native_time)
    pack_into("<2I", tracker, 0xD4, 1, 100_000_000)
    rf = bytearray(0x1C)
    pack_into("<d", rf, 8, 0.25)
    pack_into("<i", rf, 0x18, 2)
    windows = {
        "measurements": (0x331DF8, bytes(measurement_links)),
        "channels": (0x42BCB4, bytes(channel_links)),
        "row": (0x3A0000, bytes(row)),
        "tracker": (0x3B0000, bytes(tracker)),
        "rf": (0x4025C0, bytes(rf)),
    }

    (record,) = extract_dsp_tracking(windows)

    assert record.observation is not None
    assert record.observation.gps_tow_ms == 100_000_000
    if time_scale is None:
        assert record.observation.native_time_s is None
        assert record.observation.native_time_scale is None
    else:
        assert record.observation.native_time_s == pytest.approx(native_time)
        assert record.observation.native_time_scale == time_scale
