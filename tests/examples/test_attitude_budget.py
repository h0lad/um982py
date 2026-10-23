"""Tests the heading accuracy budget against ground truth."""

from __future__ import annotations

import math
import statistics

import pytest
from examples.attitude_budget import (
    Baseline,
    angle_sigma,
    attitude_budget,
    required_baseline,
)

EAST, NORTH, UP = 0.0011, 0.0051, 0.0038
LATITUDE_STD, HEIGHT_STD = 3.0805, 3.1114
ONE_DEGREE_IN_RADIANS = 0.017453292519943295
CENTIMETRE_OVER_METRE_DEGREES = 0.5729577951308232


def test_angle_sigma_is_the_length_over_the_baseline() -> None:
    assert angle_sigma(0.01, 1.0) == pytest.approx(0.01, rel=1e-12)
    assert math.degrees(angle_sigma(0.01, 1.0)) == pytest.approx(
        CENTIMETRE_OVER_METRE_DEGREES, rel=1e-12
    )


def test_required_baseline_inverts_the_angle_sigma() -> None:
    assert required_baseline(0.01, CENTIMETRE_OVER_METRE_DEGREES) == pytest.approx(
        1.0, rel=1e-12
    )
    for sigma, target in ((0.005, 0.5), (0.02, 2.0), (0.001, 0.1)):
        length = required_baseline(sigma, target)
        assert math.degrees(angle_sigma(sigma, length)) == pytest.approx(
            target, rel=1e-12
        )


def test_one_metre_baseline_with_one_centimetre_noise() -> None:
    budget = attitude_budget(Baseline(0.0, 1.0, 0.0), 0.01, 0.01)
    assert budget.heading == pytest.approx(0.0, abs=1e-12)
    assert budget.pitch == pytest.approx(0.0, abs=1e-12)
    assert budget.baseline_length == pytest.approx(1.0, rel=1e-12)
    assert budget.heading_sigma == pytest.approx(
        CENTIMETRE_OVER_METRE_DEGREES, rel=1e-12
    )
    assert budget.pitch_sigma == pytest.approx(CENTIMETRE_OVER_METRE_DEGREES, rel=1e-12)


def halton(index: int, base: int) -> float:
    result, factor = 0.0, 1.0
    while index > 0:
        factor /= base
        result += factor * (index % base)
        index //= base
    return result


def test_monte_carlo_heading_sigma_reproduces_the_budget() -> None:
    sigma = 0.01
    budget = attitude_budget(Baseline(0.0, 1.0, 0.0), sigma, sigma)
    normal = statistics.NormalDist(0.0, sigma)
    headings = [
        math.degrees(
            math.atan2(
                normal.inv_cdf(halton(index, 2)),
                1.0 + normal.inv_cdf(halton(index, 3)),
            )
        )
        for index in range(1, 20_001)
    ]
    assert statistics.stdev(headings) == pytest.approx(budget.heading_sigma, rel=0.05)


def test_pitch_sigma_uses_the_full_baseline_length() -> None:
    budget = attitude_budget(Baseline(0.0, 1.0, 1.0), 0.01, 0.01)
    assert budget.horizontal_length == pytest.approx(1.0, rel=1e-12)
    assert budget.baseline_length == pytest.approx(math.sqrt(2.0), rel=1e-12)
    assert budget.pitch_sigma == pytest.approx(
        math.degrees(0.01 / math.sqrt(2.0)), rel=1e-12
    )


def test_budget_halves_when_the_baseline_doubles() -> None:
    short = attitude_budget(Baseline(0.0, 1.0, 0.0), 0.01, 0.01)
    long = attitude_budget(Baseline(0.0, 2.0, 0.0), 0.01, 0.01)
    assert long.heading_sigma == pytest.approx(0.5 * short.heading_sigma, rel=1e-12)


def test_heading_offset_round_trips() -> None:
    budget = attitude_budget(Baseline(0.1, 1.0, 0.0), 0.01, 0.01)
    shifted = budget.with_offset(17.5)
    assert shifted.heading == pytest.approx((budget.heading - 17.5) % 360.0, abs=1e-9)
    assert shifted.with_offset(-17.5).heading == pytest.approx(budget.heading, abs=1e-9)


def test_zero_baseline_is_rejected() -> None:
    with pytest.raises(ValueError, match="baseline length"):
        angle_sigma(0.01, 0.0)
    with pytest.raises(ValueError, match="baseline length"):
        _ = Baseline(0.0, 0.0, 0.0).pitch


def test_negative_deviation_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        angle_sigma(-0.01, 1.0)


def test_required_baseline_for_one_degree_of_heading() -> None:
    length = required_baseline(0.01, 1.0)
    assert length == pytest.approx(0.01 / ONE_DEGREE_IN_RADIANS, rel=1e-12)
    assert math.degrees(angle_sigma(0.01, length)) == pytest.approx(1.0, rel=1e-12)


def test_negated_baseline_reverses_direction_without_changing_length() -> None:
    baseline = Baseline(east=1.0, north=-2.0, up=0.5)
    negated = baseline.negated()
    assert (negated.east, negated.north, negated.up) == (-1.0, 2.0, -0.5)
    assert negated.horizontal_length == pytest.approx(baseline.horizontal_length)
