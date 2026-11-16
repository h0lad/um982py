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


def test_pitch_respects_requested_length() -> None:
    result = constrain_to_length(0.0, 1.0, 0.5, 1.0)
    assert result.pitch == pytest.approx(30.0, abs=1e-9)


def test_heading_residual_wraps_at_north() -> None:
    assert heading_residual(10.0, 350.0) == pytest.approx(20.0, abs=1e-12)
    assert heading_residual(350.0, 10.0) == pytest.approx(-20.0, abs=1e-12)
    assert heading_residual(90.0, 90.0) == pytest.approx(0.0, abs=1e-12)


def test_constrain_rejects_nonpositive_length() -> None:
    with pytest.raises(ValueError, match="constrained baseline length"):
        constrain_to_length(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="constrained baseline length"):
        constrain_to_length(1.0, 0.0, 0.0, -1.0)
