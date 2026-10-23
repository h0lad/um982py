"""Tests the residual chi-square RAIM example against ground truth."""

from __future__ import annotations

import pytest
from examples.raim_fde import chi_square_threshold


def test_five_degrees_of_freedom_threshold_matches_the_published_table() -> None:
    assert chi_square_threshold(5, 0.95) == pytest.approx(11.070, abs=0.05)
    assert chi_square_threshold(10, 0.95) == pytest.approx(18.307, abs=0.05)


def test_threshold_grows_with_degrees_of_freedom_and_confidence() -> None:
    assert chi_square_threshold(8, 0.99) > chi_square_threshold(4, 0.99)
    assert chi_square_threshold(5, 0.999) > chi_square_threshold(5, 0.99)
