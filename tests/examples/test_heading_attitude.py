"""Tests the heading and attitude example."""

from __future__ import annotations

import math

import pytest
from examples.heading_attitude import (
    Attitude,
    angular_rate,
    attitude_from_enu,
    enu_from_attitude,
    heading_degrees,
    pitch_degrees,
    swapped_attitude,
    torsion,
)

UNIT_BASELINE = 1.0
HALF_UP = 0.5
THIRTY_DEGREES = 30.0
SCALE = 7.0
CARDINAL_HEADINGS = (
    (0.0, UNIT_BASELINE, 0.0),
    (UNIT_BASELINE, 0.0, 90.0),
    (0.0, -UNIT_BASELINE, 180.0),
    (-UNIT_BASELINE, 0.0, 270.0),
)


@pytest.mark.parametrize(("east", "north", "expected"), CARDINAL_HEADINGS)
def test_cardinal_baselines_give_quarter_turn_headings(
    east: float, north: float, expected: float
) -> None:
    assert heading_degrees(east, north) == pytest.approx(expected, abs=1e-12)


def test_west_wraps_to_three_quarters_of_a_turn() -> None:
    assert heading_degrees(-UNIT_BASELINE, 0.0) == pytest.approx(270.0, abs=1e-12)
    assert heading_degrees(0.0, -UNIT_BASELINE) == pytest.approx(180.0, abs=1e-12)


def test_half_metre_up_on_a_one_metre_baseline_is_thirty_degrees() -> None:
    assert pitch_degrees(HALF_UP, UNIT_BASELINE) == pytest.approx(
        THIRTY_DEGREES, abs=1e-9
    )


def test_attitude_of_a_north_baseline_tilted_by_half_a_metre() -> None:
    attitude = attitude_from_enu(0.0, math.cos(math.radians(THIRTY_DEGREES)), HALF_UP)
    assert attitude.heading == pytest.approx(0.0, abs=1e-12)
    assert attitude.pitch == pytest.approx(THIRTY_DEGREES, abs=1e-9)
    assert attitude.baseline_length == pytest.approx(UNIT_BASELINE, abs=1e-12)


def test_heading_and_pitch_are_invariant_to_baseline_scaling() -> None:
    east, north, up = 0.31, 0.72, 0.11
    single = attitude_from_enu(east, north, up)
    scaled = attitude_from_enu(SCALE * east, SCALE * north, SCALE * up)
    assert scaled.heading == pytest.approx(single.heading, abs=1e-12)
    assert scaled.pitch == pytest.approx(single.pitch, abs=1e-12)
    assert scaled.baseline_length == pytest.approx(
        SCALE * single.baseline_length, rel=1e-12
    )


def test_pitch_is_limited_to_the_vertical_and_rejects_a_null_baseline() -> None:
    assert pitch_degrees(UNIT_BASELINE, UNIT_BASELINE) == pytest.approx(90.0, abs=1e-12)
    assert pitch_degrees(2 * UNIT_BASELINE, UNIT_BASELINE) == pytest.approx(
        90.0, abs=1e-12
    )
    with pytest.raises(ValueError, match="baseline length"):
        pitch_degrees(0.0, 0.0)


def test_attitude_round_trip_reproduces_the_baseline() -> None:
    attitude = Attitude(heading=213.5, pitch=-17.25, baseline_length=2.75)
    east, north, up = enu_from_attitude(attitude)
    recovered = attitude_from_enu(east, north, up)
    assert recovered.heading == pytest.approx(attitude.heading, abs=1e-9)
    assert recovered.pitch == pytest.approx(attitude.pitch, abs=1e-9)
    assert recovered.baseline_length == pytest.approx(
        attitude.baseline_length, abs=1e-12
    )


def test_heading_rate_wraps_across_north() -> None:
    previous = attitude_from_enu(
        1.0 * math.sin(math.radians(350)), 1.0 * math.cos(math.radians(350)), 0.0
    )
    current = attitude_from_enu(
        1.0 * math.sin(math.radians(10)), 1.0 * math.cos(math.radians(10)), 0.0
    )
    assert angular_rate(previous, current, 2.0) == pytest.approx(10.0, abs=1e-9)
    assert angular_rate(current, previous, 2.0) == pytest.approx(-10.0, abs=1e-9)


def test_heading_rate_needs_a_positive_interval() -> None:
    attitude = attitude_from_enu(0.0, 1.0, 0.0)
    for interval in (0.0, -1.0, math.inf):
        with pytest.raises(ValueError, match="interval"):
            angular_rate(attitude, attitude, interval)


def test_torsion_reports_twist_and_flags_length_changes_as_non_rigid() -> None:
    reference = attitude_from_enu(0.0, 1.0, 0.0)
    twisted = attitude_from_enu(0.01, 1.0, 0.0)
    result = torsion(reference, twisted)
    assert result.heading_difference == pytest.approx(
        math.degrees(math.atan2(0.01, 1.0))
    )
    assert result.rigid
    stretched = torsion(reference, attitude_from_enu(0.01, 1.02, 0.0))
    assert stretched.baseline_ratio == pytest.approx(math.hypot(0.01, 1.02))
    assert not stretched.rigid


def test_torsion_rejects_degenerate_baselines() -> None:
    with pytest.raises(ValueError, match="positive length"):
        torsion(Attitude(0.0, 0.0, 0.0), Attitude(0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="non-negative"):
        torsion(Attitude(0.0, 0.0, 1.0), Attitude(0.0, 0.0, 1.0), length_tolerance=-1.0)


def test_swapping_antennas_adds_half_a_turn_and_mirrors_pitch() -> None:
    attitude = attitude_from_enu(1.0, 0.0, 0.5)
    swapped = swapped_attitude(attitude)
    assert swapped.heading == pytest.approx(270.0, abs=1e-12)
    assert swapped.pitch == pytest.approx(-attitude.pitch, abs=1e-12)
    assert swapped.baseline_length == pytest.approx(attitude.baseline_length)
    restored = swapped_attitude(swapped)
    assert restored.heading == pytest.approx(attitude.heading, abs=1e-12)
    assert restored.pitch == pytest.approx(attitude.pitch, abs=1e-12)
