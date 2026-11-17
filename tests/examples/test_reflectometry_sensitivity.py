"""Independent synthetic check of the optional GNSS-IR reference report."""

import math

import pytest
from examples.gnss_reflectometry import ReflectometryJoin, SatelliteSample
from examples.gnss_reflectometry.report import QualityCriteria, build_payload

from um982py.geodesy import wavelength


def test_alternative_detrending_reports_reference_error() -> None:
    frequency = 1575.42e6
    carrier = wavelength(frequency)
    rows = []
    for index in range(241):
        elevation = 5.0 + 25.0 * index / 240
        sine = math.sin(math.radians(elevation))
        cn0 = (
            40.0
            - 3.0 * sine
            + 2.0 * sine**2
            + 3.0 * math.cos(4.0 * math.pi * 2.5 * sine / carrier + 0.7)
        )
        rows.append(
            SatelliteSample(0, 1, 0, frequency, index * 5.0, elevation, 135.0, cn0)
        )
    report = build_payload(
        ReflectometryJoin(tuple(rows), ()),
        5,
        30,
        1,
        6,
        0,
        360,
        15,
        2.5,
        quality=QualityCriteria(detrend_order=1),
    )
    comparison = report["reference_comparison"]
    assert isinstance(comparison, dict)
    assert comparison["accepted_arc_count"] == 1
    assert comparison["median_error_m"] == pytest.approx(0.0, abs=0.1)
