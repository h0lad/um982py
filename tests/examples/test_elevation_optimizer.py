"""Tests the elevation optimizer example."""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path

import pytest
from examples.elevation_optimizer import (
    MINIMUM_SATELLITES_FOR_PDOP,
    SkySatellite,
    brute_force_mask,
    highest_feasible_mask,
    inverse,
    normal_matrix,
    pdop,
    pdop_at_mask,
    retained,
    sky_from_satvis_log,
)

from um982py.experimental import FirmwareLog
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

PDOP_TOLERANCE = 1e-9
"""Exact rational inputs; 1e-9 covers only floating-point accumulation."""

IDENTITY_TOLERANCE = 1e-10

HAND_COMPUTED_PDOP = math.sqrt(8 / 3)
"""Three horizon satellites 120 deg apart plus one at zenith: sqrt(2/3+2/3+4/3)."""


def spread(value: int) -> float:
    """Map an integer to a value in 0..1 by the golden-ratio sequence."""
    return (value * 0.6180339887498949) % 1.0


def synthetic(count: int, seed: int) -> tuple[SkySatellite, ...]:
    """Build a reproducible sky from a low-discrepancy sequence."""
    return tuple(
        SkySatellite(
            prn=index + 1,
            elevation=2.0 + 86.0 * spread(seed + index * 7),
            azimuth=360.0 * spread(seed * 13 + index * 29),
        )
        for index in range(count)
    )


def test_pdop_of_three_horizon_and_one_zenith_satellite_is_closed_form() -> None:
    value = pdop((0.0, 120.0, 240.0, 45.0), (0.0, 0.0, 0.0, 90.0))
    assert value == pytest.approx(HAND_COMPUTED_PDOP, abs=PDOP_TOLERANCE)


def test_inverse_times_matrix_is_the_identity() -> None:
    matrix = normal_matrix((0.0, 90.0, 200.0, 300.0), (12.0, 40.0, 65.0, 25.0))
    inverted = inverse(matrix)
    product = [
        [sum(row[i] * inverted[i][j] for i in range(4)) for j in range(4)]
        for row in matrix
    ]
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            assert product[i][j] == pytest.approx(expected, abs=IDENTITY_TOLERANCE)


def test_singular_geometry_has_no_pdop() -> None:
    matrix = normal_matrix((0.0, 0.0, 90.0, 180.0), (30.0, 30.0, 10.0, 20.0))
    with pytest.raises(ValueError):
        inverse(matrix)
    assert math.isinf(pdop((0.0, 0.0, 90.0, 180.0), (30.0, 30.0, 10.0, 20.0)))


def test_hand_computed_mask_for_four_satellites_is_the_lowest_elevation() -> None:
    satellites = (
        SkySatellite(prn=1, elevation=10.0, azimuth=0.0),
        SkySatellite(prn=2, elevation=30.0, azimuth=90.0),
        SkySatellite(prn=3, elevation=50.0, azimuth=180.0),
        SkySatellite(prn=4, elevation=70.0, azimuth=270.0),
    )
    solution = highest_feasible_mask(satellites, minimum_satellites=4)
    assert solution is not None
    assert solution.mask == pytest.approx(10.0)
    assert solution.satellites == pytest.approx(4)
    assert solution.pdop == pytest.approx(
        pdop_at_mask(satellites, 10.0), abs=PDOP_TOLERANCE
    )


def test_hand_computed_mask_for_six_satellites_is_the_fourth_elevation() -> None:
    satellites = (
        SkySatellite(prn=1, elevation=5.0, azimuth=10.0),
        SkySatellite(prn=2, elevation=20.0, azimuth=60.0),
        SkySatellite(prn=3, elevation=35.0, azimuth=110.0),
        SkySatellite(prn=4, elevation=40.0, azimuth=200.0),
        SkySatellite(prn=5, elevation=62.0, azimuth=280.0),
        SkySatellite(prn=6, elevation=78.0, azimuth=330.0),
    )
    solution = highest_feasible_mask(satellites, minimum_satellites=4)
    assert solution is not None
    assert solution.mask == pytest.approx(35.0)
    assert solution.satellites == pytest.approx(4)


def test_fractional_elevation_selects_its_whole_degree_below() -> None:
    satellites = (
        SkySatellite(prn=1, elevation=9.2, azimuth=45.0),
        SkySatellite(prn=2, elevation=10.4, azimuth=45.0),
        SkySatellite(prn=3, elevation=45.0, azimuth=0.0),
        SkySatellite(prn=4, elevation=45.0, azimuth=120.0),
        SkySatellite(prn=5, elevation=45.0, azimuth=240.0),
    )
    solution = highest_feasible_mask(satellites, minimum_satellites=4)
    assert solution is not None
    assert solution.mask == pytest.approx(10.0)
    assert solution.satellites == pytest.approx(4)


@pytest.mark.parametrize("seed", [11, 23, 41, 59, 67])
def test_optimizer_matches_the_full_grid_scan(seed: int) -> None:
    satellites = synthetic(9, seed)
    chosen = highest_feasible_mask(satellites, minimum_satellites=5)
    scanned = brute_force_mask(satellites, minimum_satellites=5)
    assert chosen is not None
    assert scanned is not None
    assert chosen.mask == pytest.approx(scanned.mask)
    assert chosen.satellites == pytest.approx(scanned.satellites)
    assert chosen.pdop == pytest.approx(scanned.pdop, abs=PDOP_TOLERANCE)


def test_raising_the_mask_never_increases_the_retained_count() -> None:
    satellites = synthetic(12, 101)
    counts = [len(retained(satellites, float(mask))) for mask in range(91)]
    assert counts[0] == pytest.approx(len(satellites))
    for lower, higher in pairwise(counts):
        assert higher <= lower


def test_adding_a_satellite_never_increases_pdop() -> None:
    satellites = synthetic(6, 202)
    base = pdop(
        [satellite.azimuth for satellite in satellites],
        [satellite.elevation for satellite in satellites],
    )
    extra = (*satellites, SkySatellite(prn=99, elevation=4.0, azimuth=17.0))
    augmented = pdop(
        [satellite.azimuth for satellite in extra],
        [satellite.elevation for satellite in extra],
    )
    assert augmented <= base + PDOP_TOLERANCE


def test_pdop_needs_four_satellites() -> None:
    satellites = synthetic(6, 303)
    with pytest.raises(ValueError):
        highest_feasible_mask(
            satellites, minimum_satellites=MINIMUM_SATELLITES_FOR_PDOP - 1
        )


def test_geometry_below_the_requirement_has_no_solution() -> None:
    assert highest_feasible_mask(synthetic(3, 404), minimum_satellites=4) is None


def test_satvis2_fixture_geometry_is_usable() -> None:
    frames = StreamDecoder().feed((FIXTURES / "captures" / "SATVIS2B.bin").read_bytes())
    satellites = tuple(
        satellite
        for message in frames
        if FirmwareLog.SATVIS2.request(binary=True).matches(message)
        for satellite in sky_from_satvis_log(FirmwareLog.SATVIS2.decode(message))
    )
    assert len(satellites) == pytest.approx(28)
    solution = highest_feasible_mask(satellites, minimum_satellites=8)
    assert solution is not None
    assert solution.mask == pytest.approx(60.0)
    assert solution.satellites == pytest.approx(8)
    assert solution.pdop == pytest.approx(
        brute_force_mask(satellites, minimum_satellites=8).pdop, abs=PDOP_TOLERANCE
    )


def test_minimum_elevation_filters_the_satvis2_frame() -> None:
    frame = next(
        message
        for message in StreamDecoder().feed(
            (FIXTURES / "captures" / "SATVIS2B.bin").read_bytes()
        )
        if FirmwareLog.SATVIS2.request(binary=True).matches(message)
    )
    record = FirmwareLog.SATVIS2.decode(frame)
    every = sky_from_satvis_log(record)
    above_thirty = sky_from_satvis_log(record, minimum_elevation=30.0)
    assert len(above_thirty) < len(every)
    assert all(satellite.elevation >= 30.0 for satellite in above_thirty)
