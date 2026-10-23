"""Tests the satellite monitor example."""

from __future__ import annotations

import csv
import io
import math

import pytest
from examples.satellite_monitor import (
    Constellation,
    constellation_of,
    latest_frames,
    sky_plot_csv,
    sky_satellites,
    visibility,
)

from conftest import FIXTURES
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

CONSTELLATION_ORDER = [
    "GPS",
    "GLONASS",
    "GALILEO",
    "BEIDOU",
    "QZSS",
    "SBAS",
    "NAVIC",
]
ASCII_ELEVATION_STEP = 0.1


def visibility_frames(binary: bool) -> list[Record]:
    name = FirmwareLog.SATVIS2.wire_name(binary=binary)
    request = FirmwareLog.SATVIS2.request(binary=binary)
    return [
        FirmwareLog.SATVIS2.decode(message)
        for message in StreamDecoder().feed(
            (FIXTURES / "captures" / (name + ".bin")).read_bytes()
        )
        if request.matches(message)
    ]


def satellite(prn: int, elevation: float, azimuth: float, field_7: float) -> Record:
    return Record(
        name="satellites",
        entries=(
            ("channel", 0),
            ("prn", prn),
            ("status", 0),
            ("elevation", elevation),
            ("azimuth", azimuth),
            ("field_6", 0.0),
            ("field_7", field_7),
        ),
    )


def frame(constellation: int, satellites: tuple[Record, ...]) -> Record:
    return Record(
        name="SATVIS2",
        entries=(
            ("constellation", constellation),
            ("flag_1", 1),
            ("flag_2", 0),
            ("count", len(satellites)),
            ("satellites", satellites),
        ),
    )


def test_binary_frames_report_the_count_of_their_message() -> None:
    records = visibility_frames(True)
    assert len(records) == 7
    for record in records:
        count = record.integer("count")
        assert len(sky_satellites(record)) == count
        assert visibility(record).count == count


def test_elevation_and_azimuth_stay_inside_the_published_ranges() -> None:
    for binary in (False, True):
        for record in visibility_frames(binary):
            for entry in sky_satellites(record):
                assert 0.0 <= entry.elevation <= 90.0
                assert 0.0 <= entry.azimuth <= 360.0


def test_constellation_order_is_the_same_for_ascii_and_binary() -> None:
    for binary in (False, True):
        labels = [
            constellation_of(record).value for record in visibility_frames(binary)
        ]
        assert labels == CONSTELLATION_ORDER


def test_system_codes_name_every_captured_constellation() -> None:
    codes = (0, 1, 5, 6, 7, 2, 9)
    labels = [Constellation.from_value(code).value for code in codes]
    assert labels == CONSTELLATION_ORDER
    with pytest.raises(ValueError):
        Constellation.from_value(4)


def test_elevation_mask_keeps_the_expected_count() -> None:
    elevations = (2.0, 5.0, 10.0, 15.0, 30.0)
    record = frame(
        0,
        tuple(
            satellite(prn, elevation, 90.0, 40.0)
            for prn, elevation in enumerate(elevations, start=1)
        ),
    )
    assert len(sky_satellites(record)) == 5
    assert len(sky_satellites(record, 10.0)) == 3
    assert len(sky_satellites(record, 30.0)) == 1
    assert len(sky_satellites(record, 31.0)) == 0


def test_field_7_statistics_reproduce_the_frame_values() -> None:
    gps = next(record for record in visibility_frames(True) if record.integer("count"))
    values = [entry.real("field_7") for entry in gps.records("satellites")]
    average = sum(values) / len(values)
    deviation = math.sqrt(
        sum((value - average) ** 2 for value in values) / (len(values) - 1)
    )
    statistics = visibility(gps).field_7
    assert statistics.mean == pytest.approx(average, abs=1e-12)
    assert statistics.minimum == pytest.approx(min(values), abs=1e-12)
    assert statistics.maximum == pytest.approx(max(values), abs=1e-12)
    assert statistics.standard_deviation == pytest.approx(deviation, abs=1e-12)


def test_ascii_elevation_matches_binary_within_the_published_step() -> None:
    ascii_frames = visibility_frames(False)
    binary_frames = visibility_frames(True)
    for ascii_frame, binary_frame in zip(ascii_frames, binary_frames, strict=True):
        ascii_angles = {
            entry.prn: entry.elevation for entry in sky_satellites(ascii_frame)
        }
        binary_angles = {
            entry.prn: entry.elevation for entry in sky_satellites(binary_frame)
        }
        for prn, elevation in ascii_angles.items():
            if prn not in binary_angles:
                continue
            assert elevation == pytest.approx(
                binary_angles[prn], abs=ASCII_ELEVATION_STEP
            )


def test_sky_plot_csv_lists_azimuth_elevation_and_prn() -> None:
    entries = [
        entry for record in visibility_frames(True) for entry in sky_satellites(record)
    ]
    rows = list(csv.reader(io.StringIO(sky_plot_csv(entries))))
    assert rows[0] == ["azimuth", "elevation", "prn"]
    assert len(rows) == 1 + len(entries)
    ordered = sorted(entries, key=lambda item: (item.constellation.value, item.prn))
    for row, entry in zip(rows[1:], ordered, strict=True):
        assert float(row[0]) == pytest.approx(entry.azimuth, abs=1e-4)
        assert float(row[1]) == pytest.approx(entry.elevation, abs=1e-4)
        assert int(row[2]) == entry.prn


def test_empty_constellation_reports_undefined_ranges() -> None:
    record = next(
        record for record in visibility_frames(True) if record.integer("count") == 0
    )
    summary = visibility(record)
    assert summary.count == 0
    assert math.isnan(summary.elevation.minimum)
    assert math.isnan(summary.azimuth.maximum)
    assert math.isnan(summary.field_7.mean)


def test_latest_frames_keep_the_last_frame_per_constellation() -> None:
    records = visibility_frames(True)
    frames = latest_frames([*records, *records])
    assert [constellation_of(record).value for record in frames] == CONSTELLATION_ORDER
    assert all(latest is records[index] for index, latest in enumerate(frames))
