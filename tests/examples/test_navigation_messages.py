"""Tests the navigation message figures against ground truth."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from examples.navigation_messages import (
    FAMILIES,
    SKY_CENTRE,
    SKY_RADIUS,
    NavigationSatellite,
    SatelliteSystem,
    kepler_elements,
    orbital_elements,
    polar_position,
    satellite_number,
    sky_plot,
    time_of_flight,
)

from um982py.capture import read_frames
from um982py.commands import Log
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures-live"
EPOCH = 399_541.0
FAMILY_COUNTS = {"GPSEPH": 20, "GALEPH": 13, "BDSEPH": 13, "GLOEPH": 10}
SVG = "{http://www.w3.org/2000/svg}"


def decoded(log: Log | FirmwareLog, path: Path) -> tuple[Record, ...]:
    found = []
    for message in read_frames(path):
        for binary in (True, False):
            if log.request(binary=binary).matches(message):
                found.append(log.decode(message))
                break
    return tuple(found)


def families() -> dict[str, tuple[Record, ...]]:
    return {name: decoded(Log(name), FIXTURES / f"{name}A.bin") for name in FAMILIES}


def markers(document: str) -> tuple[ElementTree.Element, ...]:
    root = ElementTree.fromstring(document)  # noqa: S314
    return tuple(root.findall(f'.//{SVG}circle[@class="marker"]'))


def test_every_family_is_decoded_completely() -> None:
    records = families()
    assert {name: len(family) for name, family in records.items()} == FAMILY_COUNTS
    assert sum(FAMILY_COUNTS.values()) == pytest.approx(56, abs=0)


def test_zenith_is_the_centre_and_the_horizon_is_the_rim() -> None:
    assert polar_position(0.0, 90.0) == pytest.approx(SKY_CENTRE, abs=1e-12)
    for azimuth in (0.0, 90.0, 180.0, 270.0, 37.5):
        x, y = polar_position(azimuth, 0.0)
        assert math.dist((x, y), SKY_CENTRE) == pytest.approx(SKY_RADIUS, rel=1e-12)


def test_synthetic_zenith_and_horizon_markers_land_on_the_geometry() -> None:
    zenith = NavigationSatellite(
        SatelliteSystem.GPS, 1, 26_560_000.0, 0.01, 55.0, 26_560_000.0, 0.0, 0.0, 90.0
    )
    horizon = NavigationSatellite(
        SatelliteSystem.GPS, 2, 26_560_000.0, 0.01, 55.0, 26_560_000.0, 0.0, 90.0, 0.0
    )
    zenith_marker, horizon_marker = markers(sky_plot((zenith, horizon)))
    centre = (float(zenith_marker.get("cx") or 0), float(zenith_marker.get("cy") or 0))
    edge = (float(horizon_marker.get("cx") or 0), float(horizon_marker.get("cy") or 0))
    assert centre == pytest.approx(SKY_CENTRE, abs=1e-3)
    assert math.dist(edge, SKY_CENTRE) == pytest.approx(SKY_RADIUS, abs=1e-3)


def test_galileo_semi_major_axis_is_the_square_root_of_roota() -> None:
    record = families()["GALEPH"][0]
    assert kepler_elements(record).semi_major_axis == pytest.approx(
        record.real("roota") ** 2, rel=1e-12
    )


def test_time_of_flight_vanishes_at_the_broadcast_epoch() -> None:
    gps = families()["GPSEPH"][0]
    glonass = families()["GLOEPH"][0]
    assert time_of_flight(gps, gps.real("toe")) == pytest.approx(0.0, abs=1e-9)
    assert time_of_flight(glonass, glonass.real("e_time") / 1000.0) == pytest.approx(
        0.0, abs=1e-9
    )
    assert time_of_flight(gps, EPOCH) == pytest.approx(
        EPOCH - gps.real("toe"), abs=1e-9
    )


def test_earth_fixed_velocity_needs_the_rotation_term() -> None:
    glonass = families()["GLOEPH"][0]
    position = (
        glonass.real("pos_x"),
        glonass.real("pos_y"),
        glonass.real("pos_z"),
    )
    velocity = (
        glonass.real("vel_x"),
        glonass.real("vel_y"),
        glonass.real("vel_z"),
    )
    semi_major_axis, _, _ = orbital_elements(position, velocity)
    uncorrected, _, _ = orbital_elements(position, velocity, earth_rate=0.0)
    assert semi_major_axis == pytest.approx(25_510_000.0, rel=2e-3)
    assert abs(semi_major_axis - uncorrected) > 5.0e6


def test_satellite_number_reads_every_family() -> None:
    records = families()
    assert satellite_number(records["GPSEPH"][0]) == pytest.approx(5, abs=0)
    assert satellite_number(records["GALEPH"][0]) == pytest.approx(3, abs=0)
    assert satellite_number(records["GLOEPH"][0]) == pytest.approx(38, abs=0)
    with pytest.raises(ValueError, match="satellite number"):
        satellite_number(Record("EMPTY", (("value", 1.0),)))
