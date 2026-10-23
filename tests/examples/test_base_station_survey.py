"""Tests the base station survey example against ground truth."""

from __future__ import annotations

import math
import random

import pytest
from examples.base_station_survey import (
    SurveyCriteria,
    SurveySample,
    axis_statistics,
    survey,
    weighted_mean,
)

from um982py.geodesy import ecef_from_geodetic
from um982py.stats import stddev

SYNTHETIC_GEODETIC = (52.533664703, 13.376326561, 74.0)
CENTRE = ecef_from_geodetic(*SYNTHETIC_GEODETIC)
SIGMA = 0.4
SAMPLE_COUNT = 256
SEED = 7
TIGHT_CRITERIA = SurveyCriteria(
    minimum_samples=8, horizontal_tolerance=0.05, vertical_tolerance=0.05
)
COARSE = SurveySample(x=0.0, y=0.0, z=0.0, weight=1.0)
PRECISE = SurveySample(x=1.0, y=1.0, z=1.0, weight=10.0)


def scattered_samples(seed: int, count: int, sigma: float) -> list[SurveySample]:
    """Unit-weight samples scattered around ``CENTRE`` with known sigma."""
    rng = random.Random(seed)  # noqa: S311
    return [
        SurveySample(
            x=CENTRE[0] + rng.gauss(0.0, sigma),
            y=CENTRE[1] + rng.gauss(0.0, sigma),
            z=CENTRE[2] + rng.gauss(0.0, sigma),
        )
        for _ in range(count)
    ]


def alternating_samples(
    count: int, *, horizontal: float, vertical: float
) -> list[SurveySample]:
    """Samples alternating around ``CENTRE`` by the given half spreads."""
    return [
        SurveySample(
            x=CENTRE[0] + (horizontal if index % 2 else -horizontal),
            y=CENTRE[1] + (horizontal if index % 2 else -horizontal),
            z=CENTRE[2] + (vertical if index % 2 else -vertical),
        )
        for index in range(count)
    ]


def test_weighted_mean_recovers_the_known_centre_within_the_standard_error() -> None:
    result = survey(scattered_samples(SEED, SAMPLE_COUNT, SIGMA))
    bound = 3.0 * SIGMA / math.sqrt(SAMPLE_COUNT)
    assert result.ecef == pytest.approx(CENTRE, abs=bound)


def test_equatorial_radial_scatter_is_vertical_not_horizontal() -> None:
    samples = [
        SurveySample(6378137.0 + offset, 0.0, 0.0) for offset in (-1.0, 1.0, -1.0, 1.0)
    ]
    result = survey(
        samples,
        SurveyCriteria(
            minimum_samples=4, horizontal_tolerance=0.01, vertical_tolerance=1.0
        ),
    )
    assert result.horizontal_standard_error == pytest.approx(0.0, abs=1e-12)
    assert result.up.standard_error == pytest.approx(1 / math.sqrt(3), abs=1e-12)
    assert result.converged


def test_recovered_sigma_matches_the_sample_sigma() -> None:
    samples = scattered_samples(SEED, SAMPLE_COUNT, SIGMA)
    result = survey(samples)
    reference = [stddev([sample.x for sample in samples])]
    reference.append(stddev([sample.y for sample in samples]))
    reference.append(stddev([sample.z for sample in samples]))
    assert [result.x.std, result.y.std, result.z.std] == pytest.approx(
        reference, rel=1e-12
    )
    assert result.x.std == pytest.approx(SIGMA, rel=0.1)


def test_standard_error_is_the_sigma_over_the_root_of_the_sample_count() -> None:
    samples = scattered_samples(SEED, SAMPLE_COUNT, SIGMA)
    result = survey(samples)
    expected = stddev([sample.x for sample in samples]) / math.sqrt(SAMPLE_COUNT)
    assert result.x.standard_error == pytest.approx(expected, rel=1e-12)


def test_weights_of_one_and_ten_land_on_the_exact_weighted_position() -> None:
    result = survey([COARSE, PRECISE])
    assert [result.x.mean, result.y.mean, result.z.mean] == pytest.approx(
        [10.0 / 11.0] * 3, rel=1e-15
    )
    assert result.total_weight == pytest.approx(11.0, abs=0.0)


def test_inverse_weight_shrinks_the_offset_from_the_precise_sample() -> None:
    weighted = survey([COARSE, PRECISE])
    equal = survey([COARSE, SurveySample(x=1.0, y=1.0, z=1.0)])
    assert (1.0 - equal.x.mean) / (1.0 - weighted.x.mean) == pytest.approx(
        5.5, rel=1e-12
    )


def test_converges_when_the_count_and_spread_meet_the_criteria() -> None:
    samples = alternating_samples(8, horizontal=0.01, vertical=0.01)
    assert survey(samples, TIGHT_CRITERIA).converged


def test_stays_unconverged_below_the_minimum_sample_count() -> None:
    samples = alternating_samples(7, horizontal=0.01, vertical=0.01)
    assert not survey(samples, TIGHT_CRITERIA).converged


def test_stays_unconverged_when_the_horizontal_error_exceeds_the_tolerance() -> None:
    samples = alternating_samples(8, horizontal=1.0, vertical=0.01)
    result = survey(samples, TIGHT_CRITERIA)
    assert result.horizontal_standard_error > TIGHT_CRITERIA.horizontal_tolerance
    assert not result.converged


def test_stays_unconverged_when_the_vertical_error_exceeds_the_tolerance() -> None:
    samples = alternating_samples(8, horizontal=0.01, vertical=1.0)
    result = survey(samples, TIGHT_CRITERIA)
    assert result.z.standard_error > TIGHT_CRITERIA.vertical_tolerance
    assert not result.converged


def test_geodetic_output_round_trips_through_ecef() -> None:
    centre = ecef_from_geodetic(*SYNTHETIC_GEODETIC)
    result = survey([SurveySample(*centre)])
    assert result.latitude == pytest.approx(SYNTHETIC_GEODETIC[0], abs=1e-8)
    assert result.longitude == pytest.approx(SYNTHETIC_GEODETIC[1], abs=1e-8)
    assert result.height == pytest.approx(SYNTHETIC_GEODETIC[2], abs=1e-4)


def test_a_single_sample_reports_no_spread() -> None:
    result = survey([SurveySample(x=1.0, y=2.0, z=3.0)])
    assert result.count == 1
    assert result.ecef == pytest.approx((1.0, 2.0, 3.0), abs=0.0)
    assert (result.x.std, result.x.standard_error) == (0.0, 0.0)


def test_equal_weights_reproduce_the_arithmetic_mean() -> None:
    values = [1.0, 2.0, 4.0, 8.0]
    statistics = axis_statistics(values, [1.0] * len(values))
    assert statistics.mean == pytest.approx(3.75, rel=1e-15)
    assert weighted_mean(values, [2.0] * len(values)) == pytest.approx(3.75, rel=1e-15)


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        weighted_mean([1.0, 2.0], [1.0, -1.0])
    with pytest.raises(ValueError, match="equal length"):
        weighted_mean([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="at least one"):
        weighted_mean([], [])


def test_unconverged_survey_has_explicit_status() -> None:
    from examples.base_station_survey.__main__ import payload_of

    result = survey(scattered_samples(SEED, 4, SIGMA))
    assert payload_of(result, None)["status"] == "not_converged"
