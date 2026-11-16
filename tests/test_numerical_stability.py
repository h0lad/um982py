"""Analytic regression cases that do not require a scientific runtime."""

import pytest

from um982py.stats import detrend, least_squares


@pytest.mark.parametrize("scale", [1e-40, 1.0, 1e40])
def test_qr_rank_check_is_scale_invariant(scale: float) -> None:
    rows = [[scale, scale * x] for x in (-2, -1, 0, 1, 2)]
    values = [scale * (3 + 2 * x) for x in (-2, -1, 0, 1, 2)]
    result = least_squares(rows, values, [1.0] * len(rows))
    assert result.parameters == pytest.approx((3, 2), abs=1e-12)


def test_nearly_dependent_columns_retain_their_information() -> None:
    # Normal equations lose the small independent component through cancellation.
    rows = [[1.0, 1.0 + x * 1e-7] for x in range(10)]
    values = [3 * row[0] - 2 * row[1] for row in rows]
    result = least_squares(rows, values, [1.0] * len(rows))
    assert result.parameters == pytest.approx((3, -2), abs=1e-8)
    assert result.residuals == pytest.approx([0.0] * len(rows), abs=1e-14)


@pytest.mark.parametrize("epsilon", [0.0, 1e-12])
def test_dependent_columns_are_rejected(epsilon: float) -> None:
    with pytest.raises(ValueError, match="singular or ill-conditioned"):
        least_squares([[1, 1], [1, 1 + epsilon]], [1, 2], [1, 1])


def test_detrend_high_order_polynomial_at_large_epoch() -> None:
    offsets = [i / 20 for i in range(-20, 21)]
    times = [1_700_000_000 + x for x in offsets]
    values = [sum((x - times[20]) ** k for k in range(13)) for x in times]
    assert detrend(times, values, order=12) == pytest.approx(
        [0.0] * len(times), abs=1e-11
    )


def test_detrend_rejects_nonfinite_input() -> None:
    with pytest.raises(ValueError):
        detrend([0, 1, 2], [0, float("nan"), 2])
