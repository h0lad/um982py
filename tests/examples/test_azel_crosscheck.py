"""Tests the azimuth/elevation cross-check against ground truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from examples.azel_crosscheck import (
    AzimuthElevationDifference,
    SatelliteGeometry,
    galileo_elements,
    prn_of,
    satellite_state,
    visibility_from_satvis,
)
from examples.azel_crosscheck.__main__ import epoch_seconds

from um982py.commands import Log
from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.messages.enums import SatelliteSystem
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures-live"
EPOCH_SECONDS = 399_541.0
GPS_PRN_COUNT = 20
GLONASS_PRN_COUNT = 10
GALILEO_PRN_COUNT = 13
BEIDOU_PRN_COUNT = 13


def records(log: Log) -> tuple[Record, ...]:
    """Decode every frame of one broadcast ephemeris log."""
    name = log.wire_name()
    return tuple(
        log.decode(message)
        for message in StreamDecoder().feed((FIXTURES / f"{name}.bin").read_bytes())
        if getattr(message, "name", "").startswith(name)
    )


def satvis_records() -> tuple[Record, ...]:
    """The four SATVIS2 frames of the first live epoch."""
    return tuple(
        FirmwareLog.SATVIS2.decode(message)
        for message in StreamDecoder().feed((FIXTURES / "SATVIS2A.bin").read_bytes())
        if getattr(message, "name", "").startswith("SATVIS2A")
        and float(message.header.fields[5]) == EPOCH_SECONDS
    )


def ephemerides() -> dict[SatelliteSystem, tuple[Record, ...]]:
    """Broadcast ephemerides of every supported constellation."""
    return {
        SatelliteSystem.GPS: records(Log.GPSEPH),
        SatelliteSystem.GLONASS: records(Log.GLOEPH),
        SatelliteSystem.GALILEO: records(Log.GALEPH),
        SatelliteSystem.BEIDOU: records(Log.BDSEPH),
    }


def test_ephemeris_counts_match_the_live_capture() -> None:
    systems = ephemerides()
    assert len(systems[SatelliteSystem.GPS]) == GPS_PRN_COUNT
    assert len(systems[SatelliteSystem.GLONASS]) == GLONASS_PRN_COUNT
    assert len(systems[SatelliteSystem.GALILEO]) == GALILEO_PRN_COUNT
    assert len(systems[SatelliteSystem.BEIDOU]) == BEIDOU_PRN_COUNT


def test_live_satvis_timestamp_is_the_captured_epoch() -> None:
    first = satvis_records()[0]
    assert first.message is not None
    assert epoch_seconds(first.message) == pytest.approx(EPOCH_SECONDS, abs=1e-6)


def test_satvis_count_field_matches_its_satellite_records() -> None:
    for record in satvis_records():
        assert record.integer("count") == len(record.records("satellites"))


def test_galileo_elements_recover_the_broadcast_semi_major_axis() -> None:
    record = records(Log.GALEPH)[0]
    elements = galileo_elements(record)
    assert elements.semi_major_axis == pytest.approx(
        record.real("roota") ** 2, rel=1e-15
    )
    assert elements.right_ascension == pytest.approx(record.real("omega0"), abs=1e-15)


def test_galileo_state_stays_on_the_broadcast_orbit() -> None:
    record = records(Log.GALEPH)[0]
    state = satellite_state(record, SatelliteSystem.GALILEO, EPOCH_SECONDS)
    assert 29_000_000.0 < state.radius < 30_000_000.0
    assert prn_of(record, SatelliteSystem.GALILEO) == record.integer("satid")


def test_glonass_state_uses_the_millisecond_epoch() -> None:
    record = records(Log.GLOEPH)[0]
    state = satellite_state(record, SatelliteSystem.GLONASS, EPOCH_SECONDS)
    assert 25_000_000.0 < state.radius < 26_000_000.0


def test_satvis_geometry_is_reported_without_a_range() -> None:
    first = satvis_records()[0]
    satellites = visibility_from_satvis(first)
    assert satellites
    for satellite in satellites:
        assert satellite.range == pytest.approx(0.0, abs=0.0)
        assert 0.0 <= satellite.azimuth < 360.0
        assert -90.0 <= satellite.elevation <= 90.0


def test_binary_satvis_constellations_match_ascii_names() -> None:
    fixtures = FIXTURES.parent / "captures"
    decoded = [
        tuple(
            visibility_from_satvis(FirmwareLog.SATVIS2.decode(message))
            for message in StreamDecoder().feed(
                (fixtures / f"SATVIS2{encoding}.bin").read_bytes()
            )
            if FirmwareLog.SATVIS2.request(binary=encoding == "B").matches(message)
        )
        for encoding in ("A", "B")
    ]
    assert decoded[1]
    assert {sat.system for frame in decoded[0] for sat in frame} == {
        sat.system for frame in decoded[1] for sat in frame
    }


def test_azimuth_error_wraps_across_north() -> None:
    reported = SatelliteGeometry(
        system=SatelliteSystem.GPS,
        prn=1,
        azimuth=359.5,
        elevation=45.0,
        range=0.0,
    )
    computed = SatelliteGeometry(
        system=SatelliteSystem.GPS,
        prn=1,
        azimuth=0.5,
        elevation=45.5,
        range=0.0,
    )
    difference = AzimuthElevationDifference(
        system=SatelliteSystem.GPS,
        prn=1,
        computed=computed,
        reported=reported,
    )
    assert difference.azimuth_error == pytest.approx(1.0, abs=1e-12)
    assert difference.elevation_error == pytest.approx(0.5, abs=1e-12)
    assert difference.is_within_tolerance
