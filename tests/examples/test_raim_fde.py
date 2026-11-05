"""Tests the residual chi-square RAIM example against ground truth."""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest
from examples.raim_fde import chi_square_threshold, raim_fde
from examples.wls_position import RangeMeasurement

from um982py.messages.enums import SatelliteSystem


def test_five_degrees_of_freedom_threshold_matches_the_published_table() -> None:
    assert chi_square_threshold(5, 0.95) == pytest.approx(11.070, abs=0.05)
    assert chi_square_threshold(10, 0.95) == pytest.approx(18.307, abs=0.05)


def test_threshold_grows_with_degrees_of_freedom_and_confidence() -> None:
    assert chi_square_threshold(8, 0.99) > chi_square_threshold(4, 0.99)
    assert chi_square_threshold(5, 0.999) > chi_square_threshold(5, 0.99)


def test_one_degree_of_freedom_extreme_tail() -> None:
    expected = NormalDist().inv_cdf(1 - 1e-5 / 2) ** 2
    assert chi_square_threshold(1, 1 - 1e-5) == pytest.approx(expected, rel=1e-10)


def test_undetectable_satellite_fault_invalidates_protection_levels() -> None:
    x, distance = 6378137.0, 20200000.0
    s = math.sqrt(0.75)
    observations = [
        RangeMeasurement(
            SatelliteSystem.GPS,
            i + 1,
            x + distance * 0.5,
            distance * s * math.cos(2 * math.pi * i / 5),
            distance * s * math.sin(2 * math.pi * i / 5),
            distance,
            1,
        )
        for i in range(5)
    ]
    observations.append(
        RangeMeasurement(
            SatelliteSystem.GPS,
            6,
            x - distance * 0.5,
            distance * s,
            0,
            distance + 100,
            1,
        )
    )
    result = raim_fde(observations, (x, 0, 0, 0), max_exclusions=0)
    assert not result.integrity_passed
    assert math.isinf(result.hpl) and math.isinf(result.vpl)
