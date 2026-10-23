"""Check numerical and missing-data behavior of statistical helpers."""

import math

import pytest

from um982py.stats import mean, stddev


def test_mean_preserves_small_terms_when_large_values_cancel() -> None:
    assert mean([1e16, 1.0, -1e16]) == pytest.approx(1 / 3)


def test_standard_deviation_requires_observations() -> None:
    assert math.isnan(stddev([]))
    assert math.isnan(stddev([], sample=False))
    assert math.isnan(stddev([7.0]))
    assert stddev([7.0], sample=False) == 0.0
