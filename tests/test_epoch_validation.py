"""GPS epochs must contain a valid receiver week and time of week."""

import pytest

from um982py.measurement import bdt_week_to_gps_seconds, gps_epoch
from um982py.messages import (
    AsciiHeader,
    AsciiMessage,
    BinaryHeader,
    BinaryMessage,
    LegacyAsciiHeader,
    LegacyBinaryHeader,
)


def message(header: AsciiHeader | LegacyAsciiHeader) -> AsciiMessage:
    return AsciiMessage(header, (), b"")


@pytest.mark.parametrize("milliseconds", [-1, 604800000])
def test_invalid_n4_time_of_week(milliseconds: int) -> None:
    header = AsciiHeader("BESTNAVA", 1, "GPS", "FINE", 2345, milliseconds, 0, 0, 18, 0)
    with pytest.raises(ValueError, match="week range"):
        gps_epoch(message(header))


@pytest.mark.parametrize("seconds", ["nan", "inf", "-1", "604800"])
def test_invalid_legacy_time_of_week(seconds: str) -> None:
    header = LegacyAsciiHeader("BESTNAVA", ("COM1", "0", "0", "FINE", "2345", seconds))
    with pytest.raises(ValueError, match="week range"):
        gps_epoch(message(header))


def test_week_boundary_is_valid() -> None:
    header = AsciiHeader("BESTNAVA", 1, "GPS", "FINE", 2345, 604799999, 0, 0, 18, 0)
    assert gps_epoch(message(header)) == pytest.approx(2345 * 604800 + 604799.999)


def test_incomplete_legacy_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        gps_epoch(message(LegacyAsciiHeader("BESTNAVA", ())))


def test_incomplete_legacy_binary_timestamp_is_rejected() -> None:
    frame = BinaryMessage(LegacyBinaryHeader(1, 0, bytes(19)), b"", b"")
    with pytest.raises(ValueError, match="incomplete legacy"):
        gps_epoch(frame)


def test_glonass_channel_override_does_not_require_receiver_channel() -> None:
    from um982py.measurement import gnss_range_samples
    from um982py.messages import Record

    observation = Record(
        "observation",
        (
            ("tracking_status", (1 << 16) | 0x1400),
            ("prn", 38),
            ("pseudorange", 20_000_000.0),
            ("pseudorange_std", 1.0),
            ("carrier_phase", -1000.0),
            ("carrier_phase_std", 0.1),
            ("doppler", 0.0),
            ("cn0", 40.0),
            ("lock_time", 1.0),
        ),
    )
    record = Record("RANGE", (("observations", (observation,)),))
    result = gnss_range_samples(record, epoch=1.0, glonass_channels={38: -7})
    assert len(result) == 1
    assert result[0].phase_m == pytest.approx(1000 * 299792458 / 1598062500)


def test_bdt_nominal_gps_conversion_and_week_rollover() -> None:
    from um982py import bdt_week_to_gps_seconds as exported

    assert exported is bdt_week_to_gps_seconds
    assert bdt_week_to_gps_seconds(0, 0) == 1356 * 604800 + 14
    assert bdt_week_to_gps_seconds(0, 604799.5) == 1357 * 604800 + 13.5
    assert bdt_week_to_gps_seconds(1, 0) == 1357 * 604800 + 14


@pytest.mark.parametrize(
    ("week", "seconds"), [(-1, 0), (0, -1), (0, 604800), (0, float("nan")), (True, 0)]
)
def test_invalid_bdt_week_and_seconds_rejected(week: int, seconds: float) -> None:
    with pytest.raises(ValueError):
        bdt_week_to_gps_seconds(week, seconds)


@pytest.mark.parametrize("reference", ["BDS", "UNKNOWN"])
def test_non_gps_ascii_reference_requires_explicit_week_scale(reference: str) -> None:
    header = AsciiHeader("BESTNAVA", 1, reference, "FINE", 100, 1000, 0, 0, 18, 0)
    frame = message(header)
    with pytest.raises(ValueError, match="time reference"):
        gps_epoch(frame)
    assert gps_epoch(frame, week_scale="BDT") == (100 + 1356) * 604800 + 15
    assert gps_epoch(frame, week_scale="GPST") == 100 * 604800 + 1


@pytest.mark.parametrize("reference", [1, 255])
def test_non_gps_binary_reference_requires_explicit_week_scale(reference: int) -> None:
    header = BinaryHeader(1, 2118, 0, reference, 0, 100, 1000, 0, 0, 18, 0)
    frame = BinaryMessage(header, b"", b"")
    with pytest.raises(ValueError, match="time reference"):
        gps_epoch(frame)
    assert gps_epoch(frame, week_scale="BDT") == (100 + 1356) * 604800 + 15


def test_gps_reference_ascii_and_binary_agree() -> None:
    a = AsciiHeader("BESTNAVA", 1, "GPS", "FINE", 2400, 1000, 0, 0, 18, 0)
    b = BinaryHeader(1, 2118, 0, 0, 0, 2400, 1000, 0, 0, 18, 0)
    assert gps_epoch(message(a)) == gps_epoch(BinaryMessage(b, b"", b""))


def test_rinex_does_not_silently_export_unknown_reference() -> None:
    from um982py.messages import Record
    from um982py.rinex import export_rinex

    header = AsciiHeader("RANGEA", 1, "BDS", "FINE", 100, 1000, 0, 0, 18, 0)
    record = Record("RANGE", (("observations", ()),), message(header))
    with pytest.raises(ValueError, match="time reference"):
        export_rinex((record,))
