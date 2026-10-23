"""Checks the Hatch recursion against hand arithmetic and known labels."""

import pytest

from tests.examples._specialist import TRUTH, sample
from um982py.experimental.carrier import smooth_code


@pytest.mark.parametrize(
    "window,expected", [(100, "hatch_uncapped_m"), (2, "hatch_cap2_m")]
)
def test_hatch_matches_hand_computed_recursion(window: int, expected: str) -> None:
    data = [
        sample(float(i), code=code, phase=phase, rate=1)
        for i, (code, phase) in enumerate(
            zip(TRUTH["hatch_code_m"], TRUTH["hatch_phase_m"], strict=True)
        )
    ]
    assert [
        item.smoothed_m for item in smooth_code(data, window=window)
    ] == pytest.approx(TRUTH[expected])


def test_constant_true_range_is_unbiased_despite_phase_ambiguity() -> None:
    result = smooth_code([sample(float(i), code=123, phase=10000) for i in range(8)])
    assert all(item.smoothed_m == pytest.approx(123) for item in result)


@pytest.mark.parametrize(
    "after",
    [
        sample(10, code=300),
        sample(1, code=300, lock=0.1),
        sample(1, code=300, phase=101),
    ],
)
def test_known_gap_lock_reset_and_phase_slip_restart_the_filter(after: object) -> None:
    from um982py.measurement import RangeSample

    assert isinstance(after, RangeSample)
    result = smooth_code([sample(0, code=100), after])
    assert result[-1].reset
    assert result[-1].count == 1
    assert result[-1].smoothed_m == 300


def test_duplicate_epochs_are_not_a_time_series() -> None:
    with pytest.raises(ValueError, match="increase"):
        smooth_code([sample(0), sample(0)])
