"""Checks held-out site mapping against a repeatable pattern and reversal."""

import pytest
from examples.sidereal_multipath import SkyResidual, evaluate_repeatability

from um982py.measurement import SignalKey

KEY = SignalKey(0, 1, 0)


def training() -> list[SkyResidual]:
    """A manually assigned two-cell site pattern of minus two and plus two metres."""
    return [
        SkyResidual(KEY, float(i), 10 if i < 3 else 20, 30, -2 if i < 3 else 2)
        for i in range(6)
    ]


def test_frozen_map_predicts_independent_repeat_day_exactly() -> None:
    validation = [
        SkyResidual(KEY, 86164 + i, az, 30, value)
        for i, (az, value) in enumerate(((10, -2), (20, 2), (10, -2), (20, 2)))
    ]
    result = evaluate_repeatability(training(), validation)
    assert result.coverage == 1
    assert result.raw_rms_m == 2
    assert result.corrected_rms_m == 0
    assert result.correlation == pytest.approx(1)


def test_changed_site_can_make_the_prediction_worse() -> None:
    validation = [
        SkyResidual(KEY, 86164 + i, az, 30, value)
        for i, (az, value) in enumerate(((10, 2), (20, -2), (10, 2), (20, -2)))
    ]
    result = evaluate_repeatability(training(), validation)
    assert result.corrected_rms_m == 4
    assert result.correlation == pytest.approx(-1)


def test_unseen_signal_does_not_inherit_a_different_satellites_map() -> None:
    result = evaluate_repeatability(
        training(), [SkyResidual(SignalKey(0, 2, 0), 86164, 10, 30, -2)]
    )
    assert result.matched_samples == 0
    assert result.corrected_rms_m is None


def test_training_leakage_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        evaluate_repeatability(training(), training())
