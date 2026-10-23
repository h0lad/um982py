"""Checks TDCP displacement against independent geometric and clock changes."""

from dataclasses import replace

import pytest

from tests.examples._specialist import TRUTH
from um982py.experimental.gps_motion import PhaseDifference, solve_displacement


def differences() -> list[PhaseDifference]:
    """Read the hand-computed carrier differences from the truth table."""
    return [
        PhaseDifference(i + 1, tuple(direction), phase, geometry, clock)
        for i, (direction, phase, geometry, clock) in enumerate(
            zip(
                TRUTH["directions"],
                TRUTH["carrier_change_m"],
                TRUTH["geometric_change_m"],
                TRUTH["satellite_clock_change_m"],
                strict=True,
            )
        )
    ]


def test_recovers_known_displacement_without_ambiguity_estimation() -> None:
    result = solve_displacement(differences(), interval=TRUTH["interval_seconds"])
    assert result.displacement_m == pytest.approx(TRUTH["displacement_m"], abs=1e-12)
    assert result.velocity_mps == pytest.approx(TRUTH["velocity_mps"], abs=1e-10)
    assert result.clock_change_m == pytest.approx(TRUTH["clock_change_m"], abs=1e-12)


def test_clock_change_does_not_alias_into_displacement() -> None:
    shifted = [
        replace(item, phase_change_m=item.phase_change_m + 1000)
        for item in differences()
    ]
    result = solve_displacement(shifted, interval=1)
    assert result.displacement_m == pytest.approx(TRUTH["displacement_m"], abs=1e-10)
    assert result.clock_change_m == pytest.approx(1000.04)


@pytest.mark.parametrize("interval", [0, -1, float("nan")])
def test_invalid_time_difference_has_no_solution(interval: float) -> None:
    with pytest.raises(ValueError):
        solve_displacement(differences(), interval=interval)
