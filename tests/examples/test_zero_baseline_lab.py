"""Checks double differences against independently assigned receiver errors."""

from dataclasses import replace

import pytest
from examples.zero_baseline_lab import double_differences, estimate_noise

from tests.examples._specialist import sample


def test_dd_statistics_match_hand_computed_three_sample_errors() -> None:
    first, second = [], []
    for i, error in enumerate((-2.0, 0.0, 2.0)):
        first += [
            sample(float(i), prn=1),
            sample(float(i), prn=2, code=100 + error, phase=100 + error / 100),
        ]
        second += [sample(float(i), prn=1), sample(float(i), prn=2)]
    differences = double_differences(first, second, reference_prn=1)
    assert [item.code_m for item in differences] == [-2, 0, 2]
    result = estimate_noise(differences)[0]
    assert result.code_dd_std_m == 2
    assert result.phase_dd_std_m == pytest.approx(0.02)
    assert result.equal_receiver_code_std_m == 1
    assert result.equal_receiver_phase_std_m == pytest.approx(0.01)
    assert result.code_sigma_ratio == 1
    assert result.phase_sigma_ratio == pytest.approx(1)


def test_common_receiver_clocks_cancel_in_the_double_difference() -> None:
    first = [sample(0, prn=prn, code=100 + 1234, phase=100 + 1234) for prn in (1, 2)]
    second = [sample(0, prn=prn, code=100 - 9876, phase=100 - 9876) for prn in (1, 2)]
    result = double_differences(first, second, reference_prn=1)[0]
    assert result.code_m == result.phase_m == 0


def test_disjoint_receiver_times_are_not_joined() -> None:
    first = [sample(0, prn=prn) for prn in (1, 2)]
    second = [sample(0.1, prn=prn) for prn in (1, 2)]
    assert not double_differences(first, second, reference_prn=1)


def test_asynchronous_receiver_epochs_cannot_be_used_as_noise() -> None:
    first = [sample(0, prn=prn) for prn in (1, 2)]
    second = [sample(0.1, prn=prn) for prn in (1, 2)]
    with pytest.raises(ValueError, match="exactly synchronized"):
        double_differences(first, second, reference_prn=1, tolerance=0.2)


def test_reference_phase_reset_breaks_every_dependent_arc() -> None:
    first = [sample(epoch, prn=prn) for epoch in (0.0, 1.0, 2.0) for prn in (1, 2)]
    first[2] = replace(first[2], lock_seconds=0.1)
    result = double_differences(first, first, reference_prn=1)
    assert [item.arc for item in result] == [1, 2, 2]
