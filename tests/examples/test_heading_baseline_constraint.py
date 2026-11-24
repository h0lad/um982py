"""Tests for heading_baseline_constraint helpers."""

from __future__ import annotations

import math

import pytest
from examples.heading_baseline_constraint import (
    constrain_to_length,
    heading_residual,
)


def test_constrained_length_matches_requested_length() -> None:
    result = constrain_to_length(0.3, 0.4, 0.1, 1.0)
    assert result.baseline_length == pytest.approx(1.0, abs=1e-12)
    assert result.unconstrained_length == pytest.approx(0.509901951, abs=1e-9)
    # Horizontal direction is preserved.
    assert math.atan2(0.3, 0.4) == pytest.approx(
        math.radians(result.heading), abs=1e-12
    )


def test_pitch_preserves_the_baseline_direction() -> None:
    result = constrain_to_length(0.0, 1.0, 0.5, 1.0)
    assert result.pitch == pytest.approx(math.degrees(math.atan2(0.5, 1.0)), abs=1e-9)


def test_long_up_component_keeps_its_heading() -> None:
    result = constrain_to_length(0.3, 0.4, 2.0, 1.0)
    assert result.heading == pytest.approx(math.degrees(math.atan2(0.3, 0.4)))


def test_heading_residual_wraps_at_north() -> None:
    assert heading_residual(10.0, 350.0) == pytest.approx(20.0, abs=1e-12)
    assert heading_residual(350.0, 10.0) == pytest.approx(-20.0, abs=1e-12)
    assert heading_residual(90.0, 90.0) == pytest.approx(0.0, abs=1e-12)


def test_constrain_rejects_nonpositive_length() -> None:
    with pytest.raises(ValueError, match="constrained baseline length"):
        constrain_to_length(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="constrained baseline length"):
        constrain_to_length(1.0, 0.0, 0.0, -1.0)


def test_length_sigma_flags_a_baseline_that_contradicts_the_separation() -> None:
    # Live 2026-11-24 BSLNENUHD (NARROW_FLOAT): 1.26 m for antennas about
    # 0.06 m apart; the ENU sigmas make the contradiction tens of sigma.
    from examples.heading_baseline_constraint import constrain_to_length, length_sigma

    components = (-0.6150, -0.0074, 1.0983)
    sigma = length_sigma(components, (0.2365, 0.1707, 0.1815))
    attitude = constrain_to_length(*components, 0.06)
    score = (attitude.unconstrained_length - 0.06) / sigma
    assert 0.18 < sigma < 0.22
    assert score > 5.0
