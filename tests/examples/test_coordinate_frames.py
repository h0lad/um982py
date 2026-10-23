"""Tests the coordinate frames example."""

from __future__ import annotations

import math

import pytest
from examples.coordinate_frames import (
    Baseline,
    Geodetic,
    antenna_position,
    enu_to_ecef,
)

from um982py.geodesy import WGS84_A, WGS84_F

ELLIPSOID_ORIGIN = Geodetic(0.0, 0.0, 0.0)
NORTH_POLE_HEIGHT = 6_356_752.314245


def test_equator_origin_sits_on_the_semi_major_axis() -> None:
    assert ELLIPSOID_ORIGIN.ecef() == pytest.approx((WGS84_A, 0.0, 0.0), abs=1e-9)


def test_north_pole_sits_on_the_semi_minor_axis() -> None:
    x, y, z = Geodetic(90.0, 0.0, 0.0).ecef()
    assert z == pytest.approx(NORTH_POLE_HEIGHT, abs=1e-6)
    assert z == pytest.approx(WGS84_A * (1 - WGS84_F), abs=1e-6)
    assert x == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-9)


def test_geodetic_round_trip_returns_the_input() -> None:
    position = Geodetic.from_ecef(*Geodetic(45.0, 45.0, 123.4).ecef())
    assert position.latitude == pytest.approx(45.0, abs=1e-9)
    assert position.longitude == pytest.approx(45.0, abs=1e-9)
    assert position.height == pytest.approx(123.4, abs=1e-6)


def test_east_offset_rotates_onto_the_east_axis() -> None:
    delta = enu_to_ecef(100.0, 0.0, 0.0, 0.0, 0.0)
    assert delta == pytest.approx((0.0, 100.0, 0.0), abs=1e-6)
    baseline = Baseline.from_ecef(delta, origin=ELLIPSOID_ORIGIN)
    assert baseline.east == pytest.approx(100.0, abs=1e-6)
    assert baseline.north == pytest.approx(0.0, abs=1e-6)
    assert baseline.up == pytest.approx(0.0, abs=1e-6)


def test_antenna_position_keeps_the_baseline_length() -> None:
    antenna = antenna_position(ELLIPSOID_ORIGIN, Baseline(100.0, 0.0, 0.0))
    distance = math.dist(ELLIPSOID_ORIGIN.ecef(), antenna.ecef())
    assert distance == pytest.approx(100.0, abs=1e-6)


def test_pure_north_baseline_has_zero_azimuth() -> None:
    baseline = Baseline.between(ELLIPSOID_ORIGIN, Geodetic(0.001, 0.0, 0.0))
    assert baseline.east == pytest.approx(0.0, abs=1e-9)
    assert baseline.azimuth == pytest.approx(0.0, abs=1e-9)


def test_pure_east_baseline_has_a_right_angle_azimuth() -> None:
    baseline = Baseline.between(ELLIPSOID_ORIGIN, Geodetic(0.0, 0.001, 0.0))
    assert baseline.north == pytest.approx(0.0, abs=1e-9)
    assert baseline.azimuth == pytest.approx(90.0, abs=1e-9)


def test_diagonal_baseline_reports_azimuth_zero_and_elevation_45() -> None:
    baseline = Baseline(0.0, 100.0, 100.0)
    assert baseline.length == pytest.approx(math.sqrt(20_000.0), abs=1e-9)
    assert baseline.azimuth == pytest.approx(0.0, abs=1e-9)
    assert baseline.elevation == pytest.approx(45.0, abs=1e-9)
