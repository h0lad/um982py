"""Invalid carrier frequencies must not create misleading measurements."""

import pytest

from um982py.geodesy import (
    dms_to_degrees,
    ecef_from_geodetic,
    geodetic_from_ecef,
    haversine_distance,
    wavelength,
)


@pytest.mark.parametrize(
    "frequency", [True, 0.0, -1.0, float("nan"), float("inf"), float("-inf")]
)
def test_wavelength_rejects_invalid_frequency(frequency: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        wavelength(frequency)


def test_wavelength_for_gps_l1() -> None:
    assert wavelength(1575420000.0) == pytest.approx(0.190293672798, abs=1e-12)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), float("-inf")])
def test_distance_rejects_nonfinite_coordinates(coordinate: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        haversine_distance(coordinate, 0, 0, 0)


def test_distance_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(ValueError, match="latitude"):
        haversine_distance(91, 0, 0, 0)
    with pytest.raises(ValueError, match="longitude"):
        haversine_distance(0, 0, 0, 181)


@pytest.mark.parametrize(
    ("coordinates", "error"),
    [
        ((91, 0, 0, float("nan")), "coordinates must be finite"),
        ((0, 181, float("inf"), 0), "coordinates must be finite"),
        ((91, 181, 0, 0), "latitude must be"),
        ((0, 181, 91, 0), "latitude must be"),
    ],
)
def test_distance_validation_error_precedence(
    coordinates: tuple[float, float, float, float], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        haversine_distance(*coordinates)


def test_distance_accepts_boolean_coordinates() -> None:
    assert haversine_distance(True, False, 0, 0) == haversine_distance(1, 0, 0, 0)


def test_distance_handles_antipodes() -> None:
    assert haversine_distance(0, 0, 0, 180) == pytest.approx(20015114.442, abs=0.001)


@pytest.mark.parametrize(
    "coordinates", [(float("nan"), 0, 0), (0, 0, float("inf")), (91, 0, 0), (0, 181, 0)]
)
def test_ecef_rejects_invalid_geodetic_coordinates(
    coordinates: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError):
        ecef_from_geodetic(*coordinates)


def test_geodetic_from_ecef_rejects_nonfinite_coordinates() -> None:
    with pytest.raises(ValueError, match="finite"):
        geodetic_from_ecef(float("nan"), 0, 0)


def test_basic_geodesy_without_optional_dependencies() -> None:
    assert ecef_from_geodetic(0, 0, 0) == pytest.approx((6378137, 0, 0))
    xyz = ecef_from_geodetic(52, 13, 50)
    assert geodetic_from_ecef(*xyz) == pytest.approx((52, 13, 50), abs=1e-6)
    assert haversine_distance(0, 0, 0, 1) == pytest.approx(111195.08, abs=0.01)


def test_dms_rejects_invalid_minutes_and_nonfinite_input() -> None:
    assert dms_to_degrees(-4807.038) == pytest.approx(-48.1173)
    for value in (4860.0, -1260.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            dms_to_degrees(value)
