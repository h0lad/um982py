"""Tests the orbit propagator against ground truth."""

from __future__ import annotations

import math
import subprocess
import sys

import pytest
from examples.ephemeris_orbit import (
    EARTH_ROTATION_RATE,
    MU,
    KeplerElements,
    SatelliteState,
    azimuth_elevation,
    orbit_state,
    solve_kepler,
)

from um982py.geodesy import ecef_from_geodetic

PAPER_X, PAPER_Y, PAPER_Z = 19_960_559.708, 6_287_146.678, 16_433_598.090
PAPER_RADIUS = 26_608_556.958
PAPER_RANGE = 20_349_649.659
PAPER_OBSERVER = (4_081_882.424, 1_410_011.130, 4_678_199.424)
PAPER_EARTH_RATE = 7.2921157e-5


def paper_elements() -> KeplerElements:
    """PRN 11 elements from the published worked example (week 1337, toe 14400)."""
    return KeplerElements(
        semi_major_axis=5153.68885040**2,
        eccentricity=4.392384667880e-3,
        mean_anomaly=1.94787600,
        argument_of_perigee=0.2339967413720,
        inclination=0.9002982524,
        right_ascension=-1.09222818,
        delta_n=6.677063840800e-9,
        idot=-3.314423773340e-10,
        omega_dot=-9.302887502600e-9,
        cuc=-1.553446054460e-6,
        cus=3.330409526820e-6,
        crc=283.21875,
        crs=-31.96875,
        cic=-8.754432201390e-8,
        cis=1.434236764910e-7,
        toe=14400.0,
    )


def test_published_example_reproduces_satellite_position() -> None:
    state = orbit_state(paper_elements(), 300.0, earth_rate=PAPER_EARTH_RATE)
    assert state.x == pytest.approx(PAPER_X, abs=0.5)
    assert state.y == pytest.approx(PAPER_Y, abs=0.5)
    assert state.z == pytest.approx(PAPER_Z, abs=0.5)


def test_local_zenith_uses_geodetic_latitude() -> None:
    latitude, longitude = 45.0, 30.0
    observer = ecef_from_geodetic(latitude, longitude, 0.0)
    phi, lam = math.radians(latitude), math.radians(longitude)
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    position = tuple(
        value + 20_000_000 * direction
        for value, direction in zip(observer, up, strict=True)
    )
    state = SatelliteState(
        *position, 0.0, math.sqrt(sum(value * value for value in position))
    )
    _, elevation, distance = azimuth_elevation(state, observer)
    assert elevation == pytest.approx(90.0, abs=1e-9)
    assert distance == pytest.approx(20_000_000, abs=1e-6)


def test_backward_glonass_propagation_is_bounded() -> None:
    code = """from examples.ephemeris_orbit import GlonassElements, glonass_state
elements = GlonassElements(25000000, 0, 1000000, 0, 3000, 0, 0, 0, 0, 0, 0, 0)
state = glonass_state(elements, -120)
assert state.y < 0
assert 24000000 < state.radius < 26000000
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=3)


def test_published_example_reproduces_orbital_radius() -> None:
    state = orbit_state(paper_elements(), 300.0, earth_rate=PAPER_EARTH_RATE)
    assert state.radius == pytest.approx(PAPER_RADIUS, abs=0.001)


def test_published_example_reproduces_slant_range() -> None:
    state = orbit_state(paper_elements(), 300.0, earth_rate=PAPER_EARTH_RATE)
    _, _, slant = azimuth_elevation(state, PAPER_OBSERVER)
    assert slant == pytest.approx(PAPER_RANGE, abs=0.01)


def test_kepler_solver_satisfies_keplers_equation() -> None:
    for mean_anomaly in (0.0, 0.5, 1.99, 3.14, -1.2):
        for eccentricity in (0.0, 0.005, 0.3, 0.7):
            anomaly = solve_kepler(mean_anomaly, eccentricity)
            residual = anomaly - eccentricity * math.sin(anomaly) - mean_anomaly
            assert abs(residual) < 1e-12


def test_kepler_solver_rejects_invalid_eccentricity() -> None:
    with pytest.raises(ValueError, match="eccentricity"):
        solve_kepler(1.0, 1.0)


def test_mean_motion_matches_the_published_value() -> None:
    elements = paper_elements()
    mean_motion = math.sqrt(MU / elements.semi_major_axis**3) + elements.delta_n
    assert mean_motion == pytest.approx(1.458593307e-4, rel=1e-6)


def test_azimuth_and_elevation_of_an_overhead_satellite() -> None:
    from um982py.geodesy import ecef_from_geodetic

    observer = ecef_from_geodetic(48.0, 11.0, 500.0)
    x, y, z = observer
    norm = math.sqrt(x * x + y * y + z * z)
    overhead = type("S", (), {})()
    overhead.x = x * 1.5
    overhead.y = y * 1.5
    overhead.z = z * 1.5
    azimuth, elevation, slant = azimuth_elevation(overhead, observer)  # type: ignore[arg-type]
    assert elevation == pytest.approx(90.0, abs=0.2)
    assert slant == pytest.approx(0.5 * norm, rel=1e-6)
    assert 0 <= azimuth <= 360


def test_default_earth_rate_is_the_icd_value() -> None:
    assert pytest.approx(7.2921151467e-5, rel=0) == EARTH_ROTATION_RATE
