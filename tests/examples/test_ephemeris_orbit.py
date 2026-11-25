import math
import subprocess
import sys
from pathlib import Path

import pytest

from um982py.commands import Log
from um982py.experimental.orbit import (
    BEIDOU_GEO_PRNS,
    EARTH_ROTATION_RATE,
    EARTH_ROTATION_RATE_BEIDOU,
    MU,
    MU_GALILEO_BEIDOU,
    MU_GLONASS,
    KeplerElements,
    SatelliteState,
    azimuth_elevation,
    clock_correction,
    orbit_state,
    solve_kepler,
    state_from_record,
    system_of,
)
from um982py.geodesy import ecef_from_geodetic
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures-live"


def records(name: str) -> list:
    return [
        Log(name).decode(message)
        for message in StreamDecoder().feed((FIXTURES / f"{name}A.bin").read_bytes())
        if getattr(message, "name", "").startswith(name)
    ]


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
    code = """from um982py.experimental.orbit import GlonassElements, glonass_state
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


def test_constellation_constants_follow_their_own_icds() -> None:
    # IS-GPS-200, Galileo OS SIS ICD, BeiDou B1I ICD and GLONASS PZ-90 ICD.
    assert MU == 3.986005e14
    assert MU_GALILEO_BEIDOU == 3.986004418e14
    assert MU_GLONASS == 3.9860044e14
    assert EARTH_ROTATION_RATE_BEIDOU == 7.292115e-5
    assert system_of(records("GALEPH")[0]) == "GALILEO"
    assert system_of(records("BDSEPH")[0]) == "BEIDOU"
    assert system_of(records("GPSEPH")[0]) == "GPS"


def test_galileo_inav_only_uses_the_inav_clock_and_bgd() -> None:
    """F/NAV clock fields are zero when only I/NAV was received (Galileo ICD)."""
    record = next(r for r in records("GALEPH") if str(r["fnavreceived"]) == "FALSE")
    elements = KeplerElements.from_record(record)
    assert elements.af0 == pytest.approx(record.real("inavaf0"), abs=0.0)
    assert elements.af1 == pytest.approx(record.real("inavaf1"), abs=0.0)
    assert elements.af2 == pytest.approx(record.real("inavaf2"), abs=0.0)
    assert elements.tgd == pytest.approx(record.real("e1e5bbgd"), abs=0.0)
    assert elements.toc == pytest.approx(record.real("inavt0c"), abs=0.0)
    state = state_from_record(record, 0.0)
    assert state.clock_bias == pytest.approx(elements.af0 - elements.tgd, abs=1e-9)


def test_galileo_fnav_uses_the_fnav_clock_and_bgd() -> None:
    record = next(r for r in records("GALEPH") if str(r["fnavreceived"]) == "TRUE")
    elements = KeplerElements.from_record(record)
    assert elements.af0 == pytest.approx(record.real("fnavaf0"), abs=0.0)
    assert elements.tgd == pytest.approx(record.real("e1e5abgd"), abs=0.0)


def geo_elements() -> KeplerElements:
    """Near-geostationary BDS elements fitted with the artificial -5 deg tilt."""
    return KeplerElements(
        semi_major_axis=42_164_169.6,
        eccentricity=2e-4,
        mean_anomaly=1.2,
        argument_of_perigee=0.3,
        inclination=math.radians(-4.7),
        right_ascension=-1.7,
        delta_n=1e-10,
        idot=2e-11,
        omega_dot=-3e-10,
        cuc=1e-6,
        cus=-2e-6,
        crc=100.0,
        crs=-50.0,
        cic=3e-8,
        cis=-4e-8,
        toe=396000.0,
    )


def _rtklib_bds_geo(elements: KeplerElements, tk: float) -> tuple[float, float, float]:
    """Independent transcription of the BDS-SIS-ICD GEO user algorithm.

    Same equations as RTKLIB eph2pos (SIN_5 = sin(-5 deg)).
    """
    mu, omge = MU_GALILEO_BEIDOU, EARTH_ROTATION_RATE_BEIDOU
    axis = elements.semi_major_axis
    mean = elements.mean_anomaly + (math.sqrt(mu / axis**3) + elements.delta_n) * tk
    e_anomaly = solve_kepler(mean, elements.eccentricity)
    sin_e, cos_e = math.sin(e_anomaly), math.cos(e_anomaly)
    latitude = (
        math.atan2(
            math.sqrt(1 - elements.eccentricity**2) * sin_e,
            cos_e - elements.eccentricity,
        )
        + elements.argument_of_perigee
    )
    radius = axis * (1 - elements.eccentricity * cos_e)
    inclination = elements.inclination + elements.idot * tk
    sin_2u, cos_2u = math.sin(2 * latitude), math.cos(2 * latitude)
    latitude += elements.cus * sin_2u + elements.cuc * cos_2u
    radius += elements.crs * sin_2u + elements.crc * cos_2u
    inclination += elements.cis * sin_2u + elements.cic * cos_2u
    x, y = radius * math.cos(latitude), radius * math.sin(latitude)
    cos_i = math.cos(inclination)
    node = elements.right_ascension + elements.omega_dot * tk - omge * elements.toe
    xg = x * math.cos(node) - y * cos_i * math.sin(node)
    yg = x * math.sin(node) + y * cos_i * math.cos(node)
    zg = y * math.sin(inclination)
    sin_5, cos_5 = math.sin(math.radians(-5.0)), math.cos(math.radians(-5.0))
    sin_o, cos_o = math.sin(omge * tk), math.cos(omge * tk)
    return (
        xg * cos_o + yg * sin_o * cos_5 + zg * sin_o * sin_5,
        -xg * sin_o + yg * cos_o * cos_5 + zg * cos_o * sin_5,
        -yg * sin_5 + zg * cos_5,
    )


@pytest.mark.parametrize("prn", [1, 5, 59, 63])
@pytest.mark.parametrize("tk", [0.0, 1234.5, -3600.0, 7200.0])
def test_beidou_geo_rotation_matches_the_icd(prn: int, tk: float) -> None:
    elements = geo_elements()
    state = orbit_state(elements, tk, system="BEIDOU", prn=prn)
    assert math.dist((state.x, state.y, state.z), _rtklib_bds_geo(elements, tk)) < 1e-6


def test_beidou_meo_does_not_use_the_geo_rotation() -> None:
    elements = geo_elements()
    geo = orbit_state(elements, 1234.5, system="BEIDOU", prn=3)
    meo = orbit_state(elements, 1234.5, system="BEIDOU", prn=20)
    assert math.dist((geo.x, geo.y, geo.z), (meo.x, meo.y, meo.z)) > 1000.0
    assert 20 not in BEIDOU_GEO_PRNS


def test_orbit_state_uses_constellation_mu_for_the_clock() -> None:
    elements = geo_elements()
    tk = 1234.5
    mean = (
        elements.mean_anomaly
        + (
            math.sqrt(MU_GALILEO_BEIDOU / elements.semi_major_axis**3)
            + elements.delta_n
        )
        * tk
    )
    eccentric = solve_kepler(mean, elements.eccentricity)
    state = orbit_state(elements, tk, system="BEIDOU", prn=20)
    assert state.clock_bias == pytest.approx(
        clock_correction(elements, tk, eccentric, mu=MU_GALILEO_BEIDOU), abs=1e-15
    )
