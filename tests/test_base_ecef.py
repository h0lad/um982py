import math

import pytest

from um982py.commands import modes


@pytest.mark.parametrize(
    ("x", "y", "z"),
    [
        (90, 181, 30001),
        (-90, 181, 30001),
        (91, 180, 30001),
        (91, -180, 30001),
        (91, 181, 30000),
        (91, 181, -30000),
        (0, 1000, 100000),
        (1000, 0, 100000),
        (1000, 1000, 0),
        (math.nextafter(90, math.inf), 181, 30001),
        (91, math.nextafter(180, math.inf), 30001),
        (91, 181, math.nextafter(30000, math.inf)),
    ],
)
def test_base_ecef_rejects_axes_outside_documented_ranges(
    x: float, y: float, z: float
) -> None:
    with pytest.raises(ValueError, match="base_position"):
        modes.base_ecef(x, y, z)


@pytest.mark.parametrize("invalid", [True, False, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("axis", range(3))
def test_base_ecef_rejects_nonfinite_or_boolean_axes(invalid: float, axis: int) -> None:
    values = [1000.0, 1000.0, 100000.0]
    values[axis] = invalid
    with pytest.raises(ValueError):
        modes.base_ecef(*values)


def test_base_ecef_accepts_values_outside_geodetic_ranges() -> None:
    assert modes.base_ecef(90.1, -180.1, 30000.1, station_id=1).text == (
        "MODE BASE 1 90.1 -180.1 30000.1"
    )
    assert modes.base_ecef(-2160489.0276, 4383620.1006, 4084738.111).text == (
        "MODE BASE -2160489.0276 4383620.1006 4084738.111"
    )


@pytest.mark.parametrize("height", [-30000, 30000])
def test_base_position_accepts_documented_height_bounds(height: float) -> None:
    assert modes.base_position(40, 10, height).text == f"MODE BASE 40 10 {height:g}"
