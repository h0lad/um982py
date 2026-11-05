"""Tests the weighted least-squares positioning example against ground truth."""

from __future__ import annotations

import math

import pytest
from examples.wls_position import (
    PositionSolution,
    RangeMeasurement,
    geodetic_position_error,
    solve_position,
)

from um982py.messages import Record
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


def test_formal_covariance_for_symmetric_satellite_geometry() -> None:
    radius = math.sqrt(3) * 20_000_000
    directions = ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))
    measurements = [
        RangeMeasurement(
            SatelliteSystem.GPS,
            i,
            x * 20_000_000,
            y * 20_000_000,
            z * 20_000_000,
            radius,
            2.0,
        )
        for i, (x, y, z) in enumerate(directions, 1)
    ]
    solution = solve_position(measurements, (0, 0, 0, 0))
    assert solution.ecef_standard_deviation_m == pytest.approx((math.sqrt(3),) * 3)
    assert solution.ecef_covariance_m2 is not None
    assert solution.ecef_covariance_m2[0] == pytest.approx((3, 0, 0))


def test_reference_position_must_be_computed_and_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examples.wls_position import __main__ as cli

    monkeypatch.setattr(cli, "record_epoch", lambda record: record.real("epoch"))

    def fix(epoch: float, status: str) -> Record:
        return Record(
            "BESTXYZ",
            (
                ("epoch", epoch),
                ("p_sol_status", status),
                ("p_x", 6378137.0),
                ("p_y", 0.0),
                ("p_z", 0.0),
            ),
        )

    bad, stale, valid = (
        fix(100, "INSUFFICIENT_OBS"),
        fix(90, "SOL_COMPUTED"),
        fix(100.5, "SOL_COMPUTED"),
    )
    assert cli.select_position([bad, stale, valid], 100, 1) is valid
    with pytest.raises(ValueError, match="no valid"):
        cli.select_position([bad, stale], 100, 1)


def test_ephemeris_selection_checks_health_issue_and_age() -> None:
    from examples.wls_position.__main__ import select_gps_ephemerides

    def eph(toe: float, health: int = 0, issue2: int = 1) -> Record:
        return Record(
            "GPSEPH",
            (
                ("week", 2000),
                ("toe", toe),
                ("prn", 1),
                ("health", health),
                ("iode1", 1),
                ("iode2", issue2),
            ),
        )

    epoch = 2000 * 604800 + 100000
    nearest = eph(99900)
    assert select_gps_ephemerides(
        [eph(99999, 1), eph(99998, issue2=2), eph(1000), nearest, eph(99000)], epoch
    ) == {1: nearest}


def test_ephemeris_age_uses_signal_transmit_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examples.wls_position import __main__ as cli

    ephemeris = Record(
        "GPSEPH",
        (
            ("week", 2000),
            ("toe", 92799.95),
            ("prn", 1),
            ("health", 0),
            ("iode1", 1),
            ("iode2", 1),
        ),
    )
    observation = Record("observation", (("prn", 1), ("pseudorange", 29979245.8)))
    monkeypatch.setattr(
        cli, "gps_signals", lambda *args, **kwargs: ((observation, 1.0),)
    )
    epoch = 2000 * 604800 + 100000
    assert cli.select_gps_ephemerides([ephemeris], epoch) == {}
    assert cli.select_gps_ephemerides(
        [ephemeris], epoch, ranges=Record("RANGE", ())
    ) == {1: ephemeris}


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
