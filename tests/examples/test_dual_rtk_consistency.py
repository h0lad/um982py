"""Tests for dual_rtk_consistency helpers."""

from __future__ import annotations

import pytest
from examples.dual_rtk_consistency import (
    _is_rtk_fixed,
    heading_difference,
    heading_from_enu,
    pitch_from_enu,
)


@pytest.mark.parametrize("position_type", [50, "NARROW_INT", 56, "INS_RTKFIXED"])
def test_fixed_type_requires_computed_status(position_type: int | str) -> None:
    from um982py.messages import Record

    assert _is_rtk_fixed(
        Record("BESTNAV", (("pos_type", position_type), ("p_sol_status", 0)))
    )
    assert not _is_rtk_fixed(
        Record("BESTNAV", (("pos_type", position_type), ("p_sol_status", 1)))
    )


def test_heading_from_enu_cardinal_directions() -> None:
    assert heading_from_enu(0.0, 1.0) == pytest.approx(0.0, abs=1e-12)
    assert heading_from_enu(1.0, 0.0) == pytest.approx(90.0, abs=1e-12)
    assert heading_from_enu(0.0, -1.0) == pytest.approx(180.0, abs=1e-12)
    assert heading_from_enu(-1.0, 0.0) == pytest.approx(270.0, abs=1e-12)


def test_pitch_from_enu() -> None:
    assert pitch_from_enu(0.0, 1.0) == pytest.approx(0.0, abs=1e-12)
    assert pitch_from_enu(0.5, 1.0) == pytest.approx(30.0, abs=1e-9)
    assert pitch_from_enu(-0.5, 1.0) == pytest.approx(-30.0, abs=1e-9)


def test_heading_difference_wraps() -> None:
    assert heading_difference(10.0, 350.0) == pytest.approx(20.0, abs=1e-12)
    assert heading_difference(350.0, 10.0) == pytest.approx(-20.0, abs=1e-12)
    assert heading_difference(180.0, 180.0) == pytest.approx(0.0, abs=1e-12)
