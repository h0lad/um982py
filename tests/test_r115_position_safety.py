"""R1.15 satellite identifiers and receiver height regressions."""

import pytest

from um982py.geodesy import geodetic_from_ecef, receiver_ecef
from um982py.messages import Record


def test_receiver_ecef_uses_ellipsoid_height() -> None:
    record = Record(
        "BESTPOS", (("lat", 40.0), ("lon", 10.0), ("hgt", 100.0), ("undulation", -30.0))
    )
    lat, lon, height = geodetic_from_ecef(*receiver_ecef(record))
    assert (lat, lon, height) == pytest.approx((40.0, 10.0, 70.0), abs=1e-6)


def test_receiver_ecef_requires_known_undulation() -> None:
    record = Record("BESTPOS", (("lat", 40.0), ("lon", 10.0), ("hgt", 100.0)))
    with pytest.raises(KeyError):
        receiver_ecef(record)
