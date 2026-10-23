"""Tests the weighted least-squares positioning example against ground truth."""

from __future__ import annotations

import pytest
from examples.wls_position import (
    PositionSolution,
    RangeMeasurement,
    geodetic_position_error,
    solve_position,
)

from um982py.messages.enums import SatelliteSystem


def test_geodetic_error_rotates_into_local_vertical() -> None:
    solution = PositionSolution(
        x=0.0,
        y=0.0,
        z=100.0,
        clock_bias=0.0,
        iterations=1,
        residual_norms=(0.0,),
        converged=True,
    )
    error = geodetic_position_error(solution, 90.0, 0.0, 0.0, 0.0, 0.0)
    assert error.horizontal == pytest.approx(0.0, abs=1e-9)
    assert error.vertical == pytest.approx(100.0, abs=1e-9)


def test_fewer_than_four_measurements_are_rejected() -> None:
    measurement = RangeMeasurement(
        system=SatelliteSystem.GPS,
        prn=1,
        x=20_000_000.0,
        y=0.0,
        z=0.0,
        pseudorange=20_000_000.0,
        pseudorange_std=1.0,
    )
    with pytest.raises(ValueError, match="four"):
        solve_position([measurement], (0.0, 0.0, 0.0, 0.0))


@pytest.mark.parametrize(
    "field", ["x", "y", "z", "pseudorange", "pseudorange_std", "satellite_clock"]
)
def test_nonfinite_measurements_are_rejected(field: str) -> None:
    from dataclasses import replace

    measurement = RangeMeasurement(
        SatelliteSystem.GPS, 1, 20_000_000, 0, 0, 20_000_000, 1
    )
    invalid = replace(measurement, **{field: float("nan")})
    with pytest.raises(ValueError, match="measurement values must be finite"):
        solve_position([invalid] * 4, (0, 0, 0, 0))


def test_invalid_solver_state_is_rejected() -> None:
    measurement = RangeMeasurement(
        SatelliteSystem.GPS, 1, 20_000_000, 0, 0, 20_000_000, 1
    )
    with pytest.raises(ValueError, match="initial position"):
        solve_position([measurement] * 4, (float("nan"), 0, 0, 0))
    with pytest.raises(ValueError, match="tolerance"):
        solve_position([measurement] * 4, (0, 0, 0, 0), tolerance=float("nan"))
