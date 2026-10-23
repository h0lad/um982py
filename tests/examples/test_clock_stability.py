"""Tests the clock stability example against ground truth."""

from __future__ import annotations

import random

import pytest
from examples.clock_stability import (
    NOISE_SLOPES,
    NoiseType,
    analyse,
    classify_noise,
    frequency_adev,
    frequency_deviation,
    log_log_slope,
    phase_adev,
)

SIGMA = 1e-9
SAMPLE_COUNT = 4096
SEED = 7
WHITE_FM_TOLERANCE = 0.15
SLOPE_TOLERANCE = 0.1
DRIFT_TOLERANCE = 0.15


@pytest.mark.parametrize("status", [3, "INVALID"])
def test_invalid_clock_model_cannot_produce_stability(
    status: int | str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from examples.clock_stability import __main__ as cli

    from um982py.messages import Record

    record = Record("TIME", (("clock_status", status), ("clock_offset", 0.0)))
    monkeypatch.setattr(
        cli, "capture_records", lambda *a, **kw: {"TIME": [record] * 128}
    )
    assert cli.main(["--frames", "128"]) == 1
    assert '"invalid_clock_samples": 128' in capsys.readouterr().out


def white_fm_offsets(seed: int, count: int, sigma: float) -> list[float]:
    """Integrate white frequency noise into a clock offset series in seconds."""
    rng = random.Random(seed)  # noqa: S311
    offsets = [0.0]
    for _ in range(count):
        offsets.append(offsets[-1] + rng.gauss(0.0, sigma))
    return offsets


def test_constant_offset_has_zero_phase_deviation_at_every_tau() -> None:
    pairs = phase_adev([0.25] * 1024)
    assert len(pairs) >= 8
    assert [deviation for _, deviation in pairs] == pytest.approx(
        [0.0] * len(pairs), abs=1e-18
    )


def test_constant_offset_reports_no_slope_and_no_noise_type() -> None:
    report = analyse([0.25] * 1024)
    assert report.phase_slope is None
    assert report.frequency_slope is None
    assert report.noise is None


def test_white_frequency_noise_reaches_sigma_at_tau_zero() -> None:
    offsets = white_fm_offsets(SEED, SAMPLE_COUNT, SIGMA)
    tau, deviation = frequency_deviation(offsets, 1.0)[0]
    assert tau == pytest.approx(1.0, abs=0.0)
    assert deviation == pytest.approx(SIGMA, rel=WHITE_FM_TOLERANCE)


def test_white_frequency_noise_slope_is_minus_one_half() -> None:
    report = analyse(white_fm_offsets(SEED, SAMPLE_COUNT, SIGMA))
    assert report.frequency_slope is not None
    assert report.frequency_slope == pytest.approx(-0.5, abs=SLOPE_TOLERANCE)


def test_white_frequency_noise_classifies_as_white_frequency_modulation() -> None:
    report = analyse(white_fm_offsets(SEED, SAMPLE_COUNT, SIGMA))
    assert report.noise is NoiseType.WHITE_FM


def test_frequency_ramp_slope_is_plus_one() -> None:
    offsets = [0.0]
    for index in range(512):
        offsets.append(offsets[-1] + 7e-10 * index)
    report = analyse(offsets)
    assert report.frequency_slope is not None
    assert report.frequency_slope == pytest.approx(1.0, abs=DRIFT_TOLERANCE)


def test_fitted_slope_of_a_known_power_law_is_recovered() -> None:
    pairs = [(2.0**index, 3.0 * (2.0**index) ** 0.5) for index in range(6)]
    assert log_log_slope(pairs) == pytest.approx(0.5, abs=1e-12)


def test_frequency_deviation_divides_the_phase_deviation_by_tau() -> None:
    pairs = [(1.0, 4e-9), (2.0, 8e-9)]
    assert [deviation for _, deviation in frequency_adev(pairs)] == pytest.approx(
        [4e-9, 4e-9], rel=1e-15
    )


def test_classification_table_covers_the_published_slopes() -> None:
    assert sorted(slope for _, slope in NOISE_SLOPES) == [-1.0, -0.5, 0.0, 0.5, 1.0]
    assert classify_noise(-0.52) is NoiseType.WHITE_FM
    assert classify_noise(0.9) is NoiseType.LINEAR_DRIFT
