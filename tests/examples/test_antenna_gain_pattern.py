"""Tests the antenna gain pattern example."""

from __future__ import annotations

import math

import pytest
from examples.antenna_gain_pattern import (
    Constellation,
    SkySample,
    constellation_of,
    fit_gain_pattern,
    sky_samples,
)

from um982py.messages import Record
from um982py.stats import percentile

TRUE_ZENITH_CN0 = 45.0
TRUE_LINEAR_ROLLOFF = 2.5
TRUE_QUADRATIC_ROLLOFF = 6.0
SYNTHETIC_NOISE_DB = 0.5
SYNTHETIC_SAMPLES = 120
SYNTHETIC_SEED = 11
REFERENCE_RANGE = 21_000_000.0
LOWEST_ELEVATION = 2.0
HIGHEST_ELEVATION = 90.0
CURVE_ELEVATIONS = (2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 75.0, 90.0)


class SeededNoise:
    def __init__(self, seed: int) -> None:
        self._state = seed

    def uniform(self) -> float:
        self._state = (1_103_515_245 * self._state + 12_345) % 2**31
        return (self._state >> 8) / 2**23

    def gauss(self, sigma: float) -> float:
        draws = [self.uniform() for _ in range(4)]
        return sigma * (sum(draws) - 2.0) * 3**0.5


def true_gain(elevation: float) -> float:
    unit = 1.0 - math.sin(math.radians(elevation))
    return TRUE_LINEAR_ROLLOFF * unit + TRUE_QUADRATIC_ROLLOFF * unit * unit


def synthetic_samples(gain_applied: bool = True) -> list[SkySample]:
    noise = SeededNoise(SYNTHETIC_SEED)
    samples = []
    for index in range(SYNTHETIC_SAMPLES):
        elevation = LOWEST_ELEVATION + index * (
            (HIGHEST_ELEVATION - LOWEST_ELEVATION) / (SYNTHETIC_SAMPLES - 1)
        )
        slant = REFERENCE_RANGE * (
            1.0 + 0.2 * math.sin(2.0 * math.pi * index / SYNTHETIC_SAMPLES)
        )
        gain = true_gain(elevation) if gain_applied else 0.0
        cn0 = (
            TRUE_ZENITH_CN0
            + gain
            - 20.0 * math.log10(slant / REFERENCE_RANGE)
            + noise.gauss(SYNTHETIC_NOISE_DB)
        )
        samples.append(
            SkySample(
                prn=index + 1,
                constellation=Constellation.GPS,
                elevation=elevation,
                azimuth=0.0,
                cn0=cn0,
                range=slant,
            )
        )
    return samples


def test_binary_visibility_frame_names_its_constellation() -> None:
    assert constellation_of(5) is Constellation.GALILEO


def test_synthetic_pattern_is_recovered_within_the_residual() -> None:
    fit = fit_gain_pattern(synthetic_samples())
    assert fit.sample_count == SYNTHETIC_SAMPLES
    assert fit.residual_rms_db == pytest.approx(SYNTHETIC_NOISE_DB, abs=0.1)
    reference = percentile([sample.range for sample in synthetic_samples()], 0.5)
    assert fit.reference_range == pytest.approx(reference, abs=1e-6)
    assert fit.zenith_cn0 == pytest.approx(
        TRUE_ZENITH_CN0 + 20.0 * math.log10(reference / REFERENCE_RANGE),
        abs=fit.residual_rms_db,
    )
    assert fit.linear_rolloff == pytest.approx(
        TRUE_LINEAR_ROLLOFF, abs=fit.residual_rms_db
    )
    assert fit.quadratic_rolloff == pytest.approx(
        TRUE_QUADRATIC_ROLLOFF, abs=fit.residual_rms_db
    )
    for elevation in CURVE_ELEVATIONS:
        assert fit.gain(elevation) == pytest.approx(
            true_gain(elevation), abs=fit.residual_rms_db
        )


def test_free_space_range_term_is_removed_before_the_fit() -> None:
    fit = fit_gain_pattern(synthetic_samples(gain_applied=False))
    assert fit.residual_rms_db == pytest.approx(SYNTHETIC_NOISE_DB, abs=0.1)
    assert fit.linear_rolloff == pytest.approx(0.0, abs=fit.residual_rms_db)
    assert fit.quadratic_rolloff == pytest.approx(0.0, abs=fit.residual_rms_db)


def test_free_space_range_term_is_exact_without_noise() -> None:
    samples = [
        SkySample(
            prn=index + 1,
            constellation=Constellation.GPS,
            elevation=10.0 * index,
            azimuth=0.0,
            cn0=TRUE_ZENITH_CN0 - 20.0 * math.log10(scale),
            range=REFERENCE_RANGE * scale,
        )
        for index, scale in enumerate((1.0, 1.1, 1.2, 0.9, 1.05, 0.95, 1.15))
    ]
    fit = fit_gain_pattern(samples)
    assert fit.residual_rms_db == pytest.approx(0.0, abs=1e-12)
    assert fit.linear_rolloff == pytest.approx(0.0, abs=1e-12)
    assert fit.quadratic_rolloff == pytest.approx(0.0, abs=1e-12)


def test_too_few_samples_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 4 samples"):
        fit_gain_pattern(synthetic_samples()[:3])


def test_sky_samples_can_select_galileo_e6_signal() -> None:
    satvis = Record(
        "SATVIS2",
        (
            ("constellation", "GALILEO"),
            (
                "satellites",
                (
                    Record(
                        "satellite",
                        (("prn", 7), ("elevation", 45.0), ("azimuth", 120.0)),
                    ),
                ),
            ),
        ),
    )
    e6_status = (3 << 16) | (22 << 21) | (1 << 12)
    range_rec = Record(
        "RANGE",
        (
            (
                "observations",
                (
                    Record(
                        "observation",
                        (
                            ("prn", 7),
                            ("tracking_status", e6_status),
                            ("cn0", 38.5),
                            ("pseudorange", 23500000.0),
                        ),
                    ),
                ),
            ),
        ),
    )
    joined = sky_samples([satvis], range_rec, system=3, signal=22)
    assert len(joined) == 1
    assert joined[0].constellation is Constellation.GALILEO
    assert joined[0].prn == 7
    assert joined[0].cn0 == 38.5
