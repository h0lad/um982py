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
