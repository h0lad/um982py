"""Tests for maritime_cog_heading helpers."""

from __future__ import annotations

import pytest
from examples.maritime_cog_heading import cog_from_positions, compute_cog_heading

from um982py.messages import Record


def test_rejects_gap_duplicates_and_zero_displacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def row(epoch: float, longitude: float, status: int = 0) -> Record:
        return Record(
            "BESTNAV",
            (
                ("epoch", epoch),
                ("lat", 0.0),
                ("lon", longitude),
                ("hor_spd", 2.0),
                ("p_sol_status", status),
                ("pos_type", 16),
            ),
        )

    monkeypatch.setattr(
        "examples.maritime_cog_heading.record_epoch",
        lambda record: record.real("epoch"),
    )
    rows = [
        row(0, 0),
        row(1, 0.01),
        row(1, 0.02),
        row(2, 0.02),
        row(20, 0.03),
        row(21, 0.04, 1),
    ]
    result = compute_cog_heading(rows, [], max_gap_s=5)
    assert result[0].cog_deg == pytest.approx(90.0)
    assert [x.unavailable_reason for x in result[1:]] == [
        "non_increasing_epoch",
        "zero_displacement",
        "gap_exceeded",
        "invalid_position",
    ]


def test_cog_north() -> None:
    assert cog_from_positions(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-9)


def test_cog_east() -> None:
    assert cog_from_positions(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=1e-9)


def test_cog_east_across_date_line() -> None:
    # Both points on the equator, moving east across the anti-meridian.
    assert cog_from_positions(0.0, 179.0, 0.0, -179.0) == pytest.approx(90.0, abs=1e-6)


def test_cog_south() -> None:
    assert cog_from_positions(1.0, 0.0, 0.0, 0.0) == pytest.approx(180.0, abs=1e-9)
