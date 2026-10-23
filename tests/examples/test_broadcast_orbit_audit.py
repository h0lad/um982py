"""Compares state anchors with hand-computed orbital-frame differences."""

import json
import math
from pathlib import Path

import pytest
from examples.broadcast_orbit_audit import (
    LIGHT_SPEED,
    RADIAL_WEIGHT,
    OrbitDifference,
    compare_state,
    signal_in_space_range_error,
    sisre_summary,
)
from examples.ephemeris_orbit import KeplerElements, orbit_state

from tests.examples._specialist import FIXTURES

ANCHORS = json.loads((FIXTURES / "rtklib-orbits.json").read_text())["cases"]


@pytest.mark.parametrize("case", ANCHORS)
def test_broadcast_state_matches_external_rtklib(case: dict[str, object]) -> None:
    from typing import Any, cast

    data = cast(dict[str, Any], case)
    elements = KeplerElements(**data["elements"])
    time = data["dt"]
    state = orbit_state(elements, time)
    assert (state.x, state.y, state.z) == pytest.approx(data["position_m"], abs=1e-5)
    assert state.clock_bias + elements.tgd == pytest.approx(
        data["clock_seconds_without_tgd"], abs=1e-15
    )
    before, after = (
        orbit_state(elements, time - 0.05),
        orbit_state(elements, time + 0.05),
    )
    velocity = (
        (after.x - before.x) / 0.1,
        (after.y - before.y) / 0.1,
        (after.z - before.z) / 0.1,
    )
    assert velocity == pytest.approx(data["velocity_mps"], abs=2e-5)


def test_rac_axes_match_a_hand_computed_equatorial_orbit() -> None:
    result = compare_state(
        "G01",
        0,
        (26000000, 0, 0),
        (25999997, -4, -12),
        (0, 1000, 0),
        broadcast_clock=2e-6,
        reference_clock=1e-6,
    )
    assert (result.radial_m, result.along_m, result.cross_m) == (3, 4, 12)
    assert result.norm_m == 13
    assert result.clock_difference_seconds == 1e-6


def test_absent_precise_clock_does_not_become_zero_clock_error() -> None:
    result = compare_state(
        "G01",
        0,
        (26000000, 0, 0),
        (26000000, 0, 0),
        (0, 1000, 0),
        broadcast_clock=2e-6,
        reference_clock=None,
    )
    assert result.clock_difference_seconds is None


def difference(
    radial: float,
    *,
    along: float = 0.0,
    cross: float = 0.0,
    clock: float | None = 0.0,
) -> OrbitDifference:
    """One orbit difference with the fields SISRE consumes."""
    return OrbitDifference(
        satellite="G01",
        epoch=0.0,
        ecef_m=(0.0, 0.0, 0.0),
        radial_m=radial,
        along_m=along,
        cross_m=cross,
        norm_m=abs(radial),
        clock_difference_seconds=clock,
    )


def test_radial_error_alone_is_weighted_by_the_documented_factor() -> None:
    assert signal_in_space_range_error(difference(1.0)) == pytest.approx(
        math.sqrt(RADIAL_WEIGHT)
    )


def test_a_clock_offset_cancels_the_radial_orbit_error() -> None:
    clock = 1.0 / LIGHT_SPEED
    assert signal_in_space_range_error(difference(1.0, clock=clock)) == pytest.approx(
        0.0, abs=1e-12
    )


def test_seven_metres_along_track_scores_one_metre_of_variance() -> None:
    score = signal_in_space_range_error(difference(0.0, along=7.0))
    assert score == pytest.approx(1.0, rel=1e-9)


def test_missing_reference_clock_cannot_be_scored() -> None:
    with pytest.raises(ValueError, match="reference clock"):
        signal_in_space_range_error(difference(1.0, clock=None))
    with pytest.raises(ValueError, match="non-negative"):
        signal_in_space_range_error(difference(1.0), radial_weight=-1.0)


def test_sisre_summary_reports_rms_and_skips_unscored_epochs() -> None:
    summary = sisre_summary(
        [difference(1.0), difference(3.0), difference(1.0, clock=None)]
    )
    assert summary.samples == 2
    assert summary.without_clock == 1
    expected = math.sqrt((RADIAL_WEIGHT * 1.0 + RADIAL_WEIGHT * 9.0) / 2.0)
    assert summary.rms_m == pytest.approx(expected)
    assert summary.maximum_m == pytest.approx(math.sqrt(RADIAL_WEIGHT * 9.0))


def test_sisre_summary_without_scored_epochs_is_not_a_number() -> None:
    summary = sisre_summary([difference(1.0, clock=None)])
    assert summary.samples == 0
    assert math.isnan(summary.rms_m)
    assert summary.without_clock == 1


def test_orbit_cli_exports_csv(tmp_path: Path) -> None:
    import csv

    from examples.broadcast_orbit_audit.__main__ import main

    output = tmp_path / "differences.csv"
    result = main(
        [
            "--replay",
            "tests/fixtures/specialist/rtklib-motion.bin",
            "--sp3",
            "tests/fixtures/specialist/rtklib-motion.sp3",
            "--json",
            str(tmp_path / "report.json"),
            "--differences-csv",
            str(output),
        ]
    )
    assert result == 0
    with output.open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(
        {"radial_m", "along_m", "cross_m"} <= row.keys() for row in rows
    )
