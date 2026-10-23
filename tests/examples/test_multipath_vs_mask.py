"""Tests the elevation-mask multipath sweep against ground truth."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
from examples.multipath_vs_mask import (
    ZENITH_MULTIPATH_METRES,
    MaskStep,
    SkySignal,
    elevated_series,
    is_falling,
    mask_step,
    mask_sweep,
    multipath_amplitude,
    synthetic_observations,
)
from examples.multipath_vs_mask.__main__ import DEFAULT_ELEVATIONS, main

PERIOD = 60.0
SAMPLES = 120
SIGNALS = tuple(
    SkySignal.at_elevation(prn, elevation) for prn, elevation in DEFAULT_ELEVATIONS
)


def series() -> tuple:
    observations = synthetic_observations(SIGNALS, period=PERIOD, samples=SAMPLES)
    return elevated_series(observations, {item.prn: item.elevation for item in SIGNALS})


def closed_form_rms(amplitudes: tuple[float, ...]) -> float:
    """RMS of a set of full sinusoids, each contributing amplitude**2 / 2."""
    return math.sqrt(sum(value**2 for value in amplitudes) / (2 * len(amplitudes)))


def test_injected_amplitude_is_the_inverse_sine_of_the_elevation() -> None:
    assert multipath_amplitude(30.0) == pytest.approx(
        2 * ZENITH_MULTIPATH_METRES, abs=1e-12
    )
    assert multipath_amplitude(90.0) == pytest.approx(
        ZENITH_MULTIPATH_METRES, abs=1e-12
    )
    assert multipath_amplitude(10.0) > multipath_amplitude(20.0)


def test_injected_amplitude_rejects_an_elevation_below_the_horizon() -> None:
    with pytest.raises(ValueError):
        multipath_amplitude(0.0)


def test_low_elevation_signal_recovers_the_closed_form_rms() -> None:
    signal = SkySignal.at_elevation(7, 30.0)
    observations = synthetic_observations((signal,), period=PERIOD, samples=SAMPLES)
    only = elevated_series(observations, {7: 30.0})
    assert len(only) == 1
    assert len(only[0].series.residuals) == SAMPLES
    expected = signal.amplitude / math.sqrt(2.0)
    assert only[0].series.rms == pytest.approx(expected, rel=1e-3)


def test_mask_sweep_falls_monotonically_on_the_injected_model() -> None:
    steps = mask_sweep(series(), (10.0, 20.0, 30.0, 40.0, 60.0, 70.0))
    assert [step.mask_degrees for step in steps] == [10.0, 20.0, 30.0, 40.0, 60.0, 70.0]
    assert is_falling(steps)
    assert all(after.rms < before.rms for before, after in itertools.pairwise(steps))


def test_pooled_rms_matches_the_closed_form_of_the_kept_signals() -> None:
    for step in mask_sweep(series(), (5.0, 15.0, 25.0)):
        kept = tuple(
            item.amplitude for item in SIGNALS if item.elevation >= step.mask_degrees
        )
        assert step.rms == pytest.approx(closed_form_rms(kept), rel=1e-3)


def test_mask_step_counts_the_signals_at_or_above_the_mask() -> None:
    steps = {
        step.mask_degrees: step for step in mask_sweep(series(), (5.0, 20.0, 50.0))
    }
    assert steps[5.0].signals == 7
    assert steps[20.0].signals == 5
    assert steps[50.0].signals == 3


def test_a_mask_above_the_whole_sky_keeps_no_signal() -> None:
    step = mask_step(89.0, series())
    assert step.signals == 0
    assert step.rms == pytest.approx(0.0, abs=1e-12)


def test_a_rising_sweep_is_not_a_falling_one() -> None:
    rising = (
        MaskStep(mask_degrees=5.0, signals=3, rms=0.5),
        MaskStep(mask_degrees=15.0, signals=2, rms=0.9),
    )
    steady = (
        MaskStep(mask_degrees=5.0, signals=3, rms=0.5),
        MaskStep(mask_degrees=15.0, signals=2, rms=0.5 + 1e-13),
    )
    assert not is_falling(rising)
    assert is_falling(steady)


def test_main_reports_a_falling_curve_for_the_injected_sweep(tmp_path: Path) -> None:
    destination = tmp_path / "sweep.json"
    assert main(["--masks", "5", "20", "--json", str(destination)]) == 0
    payload = json.loads(destination.read_text())
    assert payload["falling"]
    assert [step["mask_degrees"] for step in payload["steps"]] == [5.0, 20.0]
    assert payload["restore"] is None
