"""Reject invalid clock inputs before calculating frequency stability."""

import pytest

from um982py.stats import allan_deviation, fractional_frequency


@pytest.mark.parametrize("tau", [0.0, -1.0, float("nan"), float("inf")])
def test_clock_calculations_reject_invalid_sampling_interval(tau: float) -> None:
    with pytest.raises(ValueError, match="tau0"):
        fractional_frequency([0.0, 1.0], tau)
    with pytest.raises(ValueError, match="tau0"):
        allan_deviation([0.0, 1.0, 2.0], tau)


@pytest.mark.parametrize("sample", [float("nan"), float("inf"), float("-inf")])
def test_clock_calculations_reject_nonfinite_samples(sample: float) -> None:
    with pytest.raises(ValueError, match="phase samples"):
        fractional_frequency([0.0, sample])
    with pytest.raises(ValueError, match="frequency samples"):
        allan_deviation([0.0, sample, 1.0])
