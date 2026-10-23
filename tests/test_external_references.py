"""Optional comparisons with independent geodesy and GNSS software."""

import math
import random
import shutil
import subprocess
import warnings
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pytest
from examples.ntrip_client import ReferenceStation, gga_from_fix
from examples.rinex_navigation.__main__ import main as navigation_main

from test_extra_captures import captured
from test_rinex_rtklib import navigation, observations
from tests.examples.test_ntrip_client import station_frame
from um982py.geodesy import ecef_from_geodetic, geodetic_from_ecef
from um982py.messages.navigation import Fix
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import parse_rtcm
from um982py.protocol.checksums import rtcm_crc24q
from um982py.rinex import export_rinex
from um982py.stats import least_squares, lomb_scargle


def _proj(
    points: list[tuple[float, float, float]], *, inverse: bool
) -> list[tuple[float, ...]]:
    executable = shutil.which("cs2cs")
    if executable is None:
        pytest.skip("PROJ cs2cs is not installed")
    source, target = ("geocent", "longlat") if inverse else ("longlat", "geocent")
    command = [
        executable,
        "-f",
        "%.12f",
        f"+proj={source}",
        "+datum=WGS84",
        "+to",
        f"+proj={target}",
        "+datum=WGS84",
    ]
    result = subprocess.run(
        command,
        input="".join(f"{a} {b} {c}\n" for a, b, c in points),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return [tuple(map(float, line.split())) for line in result.stdout.splitlines()]


def test_wgs84_conversions_match_proj() -> None:
    rng = random.Random(4829)  # noqa: S311
    positions = [
        (0.0, 0.0, 0.0),
        (89.999999, 179.9, 300.0),
        (-89.999999, -179.9, -100.0),
        (0.0, 180.0, 10000.0),
    ]
    positions.extend(
        (rng.uniform(-89.9, 89.9), rng.uniform(-180, 180), rng.uniform(-500, 10000))
        for _ in range(1000)
    )
    reference = _proj([(lon, lat, h) for lat, lon, h in positions], inverse=False)
    assert len(reference) == len(positions)
    for position, xyz in zip(positions, reference, strict=True):
        assert ecef_from_geodetic(*position) == pytest.approx(xyz, rel=0, abs=1e-7)
    inverse = _proj([ecef_from_geodetic(*p) for p in positions], inverse=True)
    assert len(inverse) == len(positions)
    for position, (lon, lat, height) in zip(positions, inverse, strict=True):
        own = geodetic_from_ecef(*ecef_from_geodetic(*position))
        assert own[0] == pytest.approx(lat, rel=0, abs=1e-9)
        assert own[1] == pytest.approx(lon, rel=0, abs=1e-9)
        assert own[2] == pytest.approx(height, rel=0, abs=1e-4)


def test_rtcm_1005_and_crc_match_pyrtcm() -> None:
    pyrtcm = pytest.importorskip("pyrtcm")
    helpers = pytest.importorskip("pyrtcm.rtcmhelpers")
    frame = station_frame()
    reference = pyrtcm.RTCMReader.parse(frame)
    station = ReferenceStation.from_rtcm(parse_rtcm(frame))
    assert station is not None
    assert station.station_id == reference.DF003
    assert ecef_from_geodetic(
        station.latitude, station.longitude, station.height_m
    ) == pytest.approx(
        (reference.DF025, reference.DF026, reference.DF027), rel=0, abs=1e-5
    )
    rng = random.Random(2097)  # noqa: S311
    for length in range(101):
        data = rng.randbytes(length)
        assert rtcm_crc24q(data) == helpers.calc_crc24q(data)


@pytest.mark.parametrize("lat,lon", [(52.52, 13.405), (-45.25, 170.125), (0, -179.9)])
def test_nmea_gga_matches_pynmeagps(lat: float, lon: float) -> None:
    reference = pytest.importorskip("pynmeagps")
    fix = Fix("", lat, lon, 1, 12, 0.8, 100.0, -25.0, None, "")
    raw = gga_from_fix(fix, now=datetime(2026, 1, 1, tzinfo=UTC))
    own = Fix.from_message(parse_ascii(raw))
    other = reference.NMEAReader.parse(raw)
    assert own.latitude == pytest.approx(other.lat, abs=1e-7)
    assert own.longitude == pytest.approx(other.lon, abs=1e-7)
    assert (own.quality, own.satellites) == (other.quality, other.numSV)
    assert (own.altitude_msl, own.geoid_separation) == (other.alt, other.sep)


def test_rinex_observations_match_georinex(tmp_path: Path) -> None:
    georinex = pytest.importorskip("georinex")
    path = tmp_path / "captured.obs"
    path.write_text(export_rinex((captured("RANGE"),)).text, encoding="ascii")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        reference = georinex.load(path)
    original = observations(path)
    assert len(original) == 234
    for (_, satellite, code), value in original.items():
        assert float(reference[code].sel(sv=satellite).values[0]) == value


def test_rinex_navigation_known_fields_match_georinex(tmp_path: Path) -> None:
    georinex = pytest.importorskip("georinex")
    path = tmp_path / "captured.nav"
    capture = Path(__file__).parent / "fixtures/captures/GPSEPHA.bin"
    assert navigation_main(["--replay", str(capture), "--output", str(path)]) == 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        reference = georinex.load(path)
    records = navigation(path)
    assert len(records) == 20
    if version("georinex") == "1.16.2" and not any(
        math.isfinite(float(value)) for value in reference.SVclockBias.values.flat
    ):
        pytest.xfail("GeoRinex 1.16.2 cannot parse blank intermediate GPS NAV fields")
    names = (
        "SVclockBias",
        "SVclockDrift",
        "SVclockDriftRate",
        "IODE",
        "Crs",
        "DeltaN",
        "M0",
        "Cuc",
        "Eccentricity",
        "Cus",
        "sqrtA",
        "Toe",
        "Cic",
        "Omega0",
        "Cis",
        "Io",
        "Crc",
        "omega",
        "OmegaDot",
        "IDOT",
        "CodesL2",
        "GPSWeek",
        "L2Pflag",
        "SVacc",
        "health",
        "TGD",
        "IODC",
        "TransTime",
        "FitIntvl",
        "spare0",
        "spare1",
    )
    for (satellite, epoch), values in records.items():
        year, month, day, hour, minute, second = map(int, epoch.split())
        stamp = f"{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}"
        for name, value in zip(names, values, strict=True):
            if value is not None:
                actual = float(reference[name].sel(sv=satellite, time=stamp).values)
                assert actual == pytest.approx(value, rel=1e-13, abs=1e-15)


def test_lomb_scargle_matches_scipy_for_irregular_samples() -> None:
    signal = pytest.importorskip("scipy.signal")
    rng = random.Random(880)  # noqa: S311
    samples = sorted(rng.uniform(0, 3) for _ in range(90))
    values = [
        12 + math.sin(2 * math.pi * 1.7 * x) + rng.uniform(-0.1, 0.1) for x in samples
    ]
    frequencies = [0.05 + i * 0.1 for i in range(150)]
    mean = sum(values) / len(values)
    reference = signal.lombscargle(
        samples,
        [value - mean for value in values],
        [2 * math.pi * f for f in frequencies],
    )
    assert lomb_scargle(samples, values, frequencies) == pytest.approx(
        reference, rel=1e-11, abs=1e-11
    )


def test_weighted_least_squares_matches_numpy() -> None:
    np = pytest.importorskip("numpy")
    rng = random.Random(1441)  # noqa: S311
    rows = [[1.0, rng.uniform(-2, 2), rng.uniform(-3, 3)] for _ in range(50)]
    values = [
        row[0] * 3 + row[1] * 4 - row[2] * 2 + rng.uniform(-0.2, 0.2) for row in rows
    ]
    sigmas = [rng.uniform(0.1, 2) for _ in rows]
    design, data, sigma = np.array(rows), np.array(values), np.array(sigmas)
    parameters, _, rank, _ = np.linalg.lstsq(
        design / sigma[:, None], data / sigma, rcond=None
    )
    assert rank == 3
    result = least_squares(rows, values, sigmas)
    assert result.parameters == pytest.approx(parameters, rel=1e-12, abs=1e-12)
    assert result.residuals == pytest.approx(
        data - design @ parameters, rel=1e-12, abs=1e-12
    )
