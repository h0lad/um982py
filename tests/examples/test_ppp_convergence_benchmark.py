"""Tests for ppp_convergence_benchmark helpers."""

from __future__ import annotations

import pytest
from examples.ppp_convergence_benchmark import percentile


def test_percentile_median() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50.0) == pytest.approx(3.0, abs=1e-12)


def test_percentile_95th() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 95.0) == pytest.approx(4.8, abs=1e-12)


def test_percentile_empty() -> None:
    assert percentile([], 50.0) is None


def test_percentile_single() -> None:
    assert percentile([42.0], 50.0) == pytest.approx(42.0, abs=1e-12)


def test_reference_error_uses_the_geodetic_frame_of_the_reference() -> None:
    from examples.ppp_convergence_benchmark import _reference_error

    from um982py.geodesy import ecef_from_geodetic

    reference = ecef_from_geodetic(52.0, 13.0, 100.0)
    east, north, up = _reference_error(ecef_from_geodetic(52.0, 13.0, 101.0), reference)
    assert (east, north) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert up == pytest.approx(1.0, abs=1e-6)
