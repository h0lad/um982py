"""Exercise the public data helpers using real messages and independent values."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from struct import pack_into

import pytest

from conftest import sentence
from test_bodies import manual_message
from test_protocol import binary
from um982py.commands import Log
from um982py.decode import decode_message
from um982py.errors import ChecksumError, ProtocolError
from um982py.measurement import gps_to_utc, message_utc, range_samples, sample_series
from um982py.messages import (
    AsciiHeader,
    AsciiMessage,
    BestNavigation,
    BinaryHeader,
    BinaryMessage,
    Record,
)
from um982py.messages.enums import PositionType, SolutionStatus

FIXTURES = Path(__file__).parent / "fixtures"


def test_gps_time_to_utc_uses_supplied_leap_seconds() -> None:
    assert gps_to_utc(1930, 18.0, leap_seconds=18) == datetime(2017, 1, 1, tzinfo=UTC)
    assert gps_to_utc(1930, 18.125, leap_seconds=18) == datetime(
        2017, 1, 1, 0, 0, 0, 125000, tzinfo=UTC
    )
    assert gps_to_utc(1930, 0, leap_seconds=18) == datetime(
        2016, 12, 31, 23, 59, 42, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("week", "seconds", "leap"),
    [
        (-1, 0, 0),
        (True, 0, 0),
        (0, -1, 0),
        (0, 604800, 0),
        (0, float("nan"), 0),
        (0, True, 0),
        (0, 0, -1),
        (0, 0, True),
    ],
)
def test_gps_time_rejects_invalid_input(week: int, seconds: float, leap: int) -> None:
    with pytest.raises(ValueError):
        gps_to_utc(week, seconds, leap_seconds=leap)


def test_message_utc_accepts_record_and_requires_verified_scale() -> None:
    gps = AsciiMessage(
        AsciiHeader("BESTNAVA", 0, "GPS", "FINE", 1930, 18125, 0, 0, 18, 0),
        (),
        b"",
    )
    record = Record("BESTNAV", (), gps)
    assert message_utc(record, leap_seconds=18) == gps_to_utc(
        1930, 18.125, leap_seconds=18
    )
    bds = replace(gps, header=replace(gps.header, time_reference="BDS"))
    with pytest.raises(ValueError, match="time reference"):
        message_utc(bds, leap_seconds=18)
    assert message_utc(bds, leap_seconds=18, week_scale="BDT") == gps_to_utc(
        1930 + 1356, 32.125, leap_seconds=18
    )
    with pytest.raises(ValueError, match="timestamp"):
        message_utc(Record("BESTNAV", ()), leap_seconds=18)


def observation(system: int, signal: int, prn: int) -> Record:
    return Record(
        "observation",
        (
            ("tracking_status", (system << 16) | (signal << 21) | 0x1400),
            ("prn", prn),
            ("pseudorange", 20_000_000.0),
            ("pseudorange_std", 1.0),
            ("carrier_phase", -1000.0),
            ("carrier_phase_std", 0.1),
            ("doppler", 0.0),
            ("cn0", 40.0),
            ("lock_time", 1.0),
        ),
    )


def range_record(milliseconds: int) -> Record:
    frame = AsciiMessage(
        AsciiHeader("RANGEA", 0, "GPS", "FINE", 2400, milliseconds, 0, 0, 18, 0),
        (),
        b"",
    )
    return Record(
        "RANGE",
        (("observations", (observation(0, 0, 1), observation(3, 2, 5))),),
        frame,
    )


def test_multiconstellation_series_and_explicit_filters() -> None:
    records = (range_record(1000), range_record(2000))
    assert {s.key.system for s in range_samples(records[0])} == {0, 3}
    series = sample_series(records)
    assert {key.system for key in series} == {0, 3}
    assert all(len(samples) == 2 for samples in series.values())
    assert {key.system for key in sample_series(records, systems=(3,))} == {3}
    assert {key.signal for key in sample_series(records, signals=(0,))} == {0}
    with pytest.raises(ValueError, match="increase"):
        sample_series((records[0], records[0]))


def test_filtered_glonass_observations_do_not_require_channel_data() -> None:
    incomplete = Record(
        "observation", (("tracking_status", (1 << 16) | 0x1400), ("prn", 38))
    )
    record = Record("RANGE", (("observations", (incomplete,)),))
    assert range_samples(record, epoch=1, systems=(0,)) == ()
    assert range_samples(record, epoch=1, signals=(14,)) == ()


def test_uncompressed_obsv_observations_use_documented_units() -> None:
    record = Log.OBSVM.decode(manual_message("OBSVMA"))
    samples = range_samples(record, epoch=1)
    sample = next(
        item for item in samples if item.key.system == 0 and item.key.prn == 26
    )
    assert sample.code_m == pytest.approx(21720097.812)
    assert sample.code_std_m == pytest.approx(0.52)
    assert sample.cn0_db_hz == pytest.approx(42.7)
    assert sample.phase_m == pytest.approx(114139892.254585 * 299792458 / 1575420000)
    assert sample.phase_std_m == pytest.approx(0.0181 * 299792458 / 1575420000)

    binary_record = decode_message((FIXTURES / "bodies/OBSVHB.bin").read_bytes())
    assert range_samples(binary_record, epoch=1)


@pytest.mark.parametrize("name", ["OBSVMCMP", "OBSVHCMP", "BESTNAV"])
def test_unsupported_observation_logs_raise_useful_error(name: str) -> None:
    with pytest.raises(ValueError, match="uncompressed RANGE or OBSV"):
        range_samples(Record(name, ()), epoch=1)


def test_bestnav_status_has_identical_types_for_both_wire_formats() -> None:
    ascii_frame = manual_message("BESTNAVA")
    assert isinstance(ascii_frame, AsciiMessage)
    fields = list(ascii_frame.fields)
    fields[0], fields[1], fields[21], fields[22] = (
        "SOL_COMPUTED",
        "SINGLE",
        "SOL_COMPUTED",
        "DOPPLER_VELOCITY",
    )
    ascii_frame = replace(ascii_frame, fields=tuple(fields))
    payload = bytearray(120)
    pack_into("<II", payload, 0, 0, 16)
    pack_into("<I", payload, 36, 61)
    pack_into("<II", payload, 72, 0, 8)
    binary_frame = BinaryMessage(
        BinaryHeader(0, 2118, 120, 0, 0, 2400, 1000, 0, 0, 18, 0), bytes(payload), b""
    )
    a, b = (
        BestNavigation.from_message(ascii_frame),
        BestNavigation.from_message(binary_frame),
    )
    assert a.position_type is b.position_type is PositionType.SINGLE
    assert a.solution_status is b.solution_status is SolutionStatus.SOL_COMPUTED
    assert a.velocity_type is b.velocity_type is PositionType.DOPPLER_VELOCITY
    assert a.datum == b.datum == "WGS84"
    assert a.message is ascii_frame and b.message is binary_frame
    fields[1] = "FUTURE_MODE"
    assert (
        BestNavigation.from_message(
            replace(ascii_frame, fields=tuple(fields))
        ).position_type
        == "FUTURE_MODE"
    )
    pack_into("<I", payload, 4, 999)
    unknown = BestNavigation.from_message(replace(binary_frame, payload=bytes(payload)))
    assert unknown.position_type == 999 and not unknown.valid
    pack_into("<I", payload, 36, 12345)
    unknown = BestNavigation.from_message(replace(binary_frame, payload=bytes(payload)))
    assert unknown.datum == 12345


def test_decode_one_message_checks_length_and_checksum() -> None:
    raw = (FIXTURES / "bodies/BESTNAVA.bin").read_bytes()
    record = decode_message(raw)
    assert record.name == "BESTNAV" and record.real("lat") == pytest.approx(
        52.53369589952
    )
    assert decode_message(raw.rstrip(b"\r\n")).name == "BESTNAV"
    with pytest.raises(ProtocolError):
        decode_message(raw + raw)
    with pytest.raises(ProtocolError):
        decode_message(b"noise" + raw)
    with pytest.raises(ChecksumError):
        decode_message(raw.replace(b"BESTNAVA", b"BESTNAVB"))
    with pytest.raises(ProtocolError):
        decode_message(sentence(b"GPGGA,1,2")[:-1] + b"\nextra")


def test_decode_ambiguous_binary_requires_log() -> None:
    wire = binary(bytes(72), message_id=42)
    with pytest.raises(ProtocolError, match=r"Ambiguous.*specify log"):
        decode_message(wire)
    assert decode_message(wire, log=Log.BESTPOS).name == "BESTPOS"
    assert decode_message(wire, log=Log.BESTPOS2).name == "BESTPOS2"


def test_decode_binary_range_from_real_capture() -> None:
    wire = (FIXTURES / "captures-extra/RANGEB.bin").read_bytes()
    record = decode_message(wire)
    assert record.name == "RANGE"
    assert record.records("observations")
    with pytest.raises(ChecksumError):
        decode_message(wire[:-1] + bytes([wire[-1] ^ 1]))
