"""Tests for maritime_cog_heading helpers."""

from __future__ import annotations

import math

import pytest

from examples.maritime_cog_heading import cog_from_positions


def test_cog_north() -> None:
    assert cog_from_positions(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-9)


def test_cog_east() -> None:
    assert cog_from_positions(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=1e-9)


def test_cog_east_across_date_line() -> None:
    # Both points on the equator, moving east across the anti-meridian.
    assert cog_from_positions(0.0, 179.0, 0.0, -179.0) == pytest.approx(
        90.0, abs=1e-6
    )


def test_cog_south() -> None:
    assert cog_from_positions(1.0, 0.0, 0.0, 0.0) == pytest.approx(180.0, abs=1e-9)
