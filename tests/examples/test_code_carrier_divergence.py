"""Checks divergence filtering against the analytic response to a ramp."""

import math

import pytest

from tests.examples._specialist import sample
from um982py.experimental.carrier import monitor_divergence


def test_constant_divergence_ramp_matches_exponential_step_response() -> None:
    data = [
        sample(float(i), code=100 + 1.4 * i, phase=100 + i, rate=1) for i in range(11)
    ]
    result = monitor_divergence(data, tau=2, threshold=0.3)
    for i, item in enumerate(result[1:], 1):
        assert item.filtered_mps == pytest.approx(
            0.4 * (1 - math.exp(-i / 2)), abs=1e-13
        )
    assert next(item.epoch for item in result if item.exceeds_threshold) == 3


def test_filter_uses_elapsed_time_instead_of_sample_index() -> None:
    data = [
        sample(t, code=100 + 1.4 * t, phase=100 + t, rate=1) for t in (0.0, 0.5, 2.0)
    ]
    assert monitor_divergence(data, tau=2)[-1].filtered_mps == pytest.approx(
        0.4 * (1 - math.exp(-1))
    )


def test_new_ambiguity_does_not_become_an_ionosphere_alarm() -> None:
    result = monitor_divergence([sample(0), sample(1, phase=200)])
    assert result[-1].reset
    assert result[-1].filtered_mps is None
    assert not result[-1].exceeds_threshold
