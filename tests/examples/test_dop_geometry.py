"""Tests the DOP geometry example."""

from __future__ import annotations

import math

import pytest
from examples.dop_geometry import (
    DilutionOfPrecision,
    ReportedDilution,
    SatelliteGeometry,
    design_matrix,
    design_row,
    geometry_from_records,
    invert,
    normal_matrix,
)

from conftest import FIXTURES
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

ZENITH_AND_HORIZON = [
    *(SatelliteGeometry(0.0, 90.0) for _ in range(4)),
    SatelliteGeometry(0.0, 0.0),
    SatelliteGeometry(90.0, 0.0),
    SatelliteGeometry(180.0, 0.0),
]

NORMAL_MATRIX = (
    (1.0, 0.0, 0.0, -1.0),
    (0.0, 2.0, 0.0, 0.0),
    (0.0, 0.0, 4.0, -4.0),
    (-1.0, 0.0, -4.0, 7.0),
)

IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def frames(binary: bool) -> list[Record]:
    name = FirmwareLog.SATVIS2.wire_name(binary=binary)
    request = FirmwareLog.SATVIS2.request(binary=binary)
    return [
        FirmwareLog.SATVIS2.decode(message)
        for message in StreamDecoder().feed(
            (FIXTURES / "captures" / (name + ".bin")).read_bytes()
        )
        if request.matches(message)
    ]


def product(
    left: tuple[tuple[float, ...], ...], right: tuple[tuple[float, ...], ...]
) -> tuple[tuple[float, ...], ...]:
    size = len(left)
    return tuple(
        tuple(sum(left[i][k] * right[k][j] for k in range(size)) for j in range(size))
        for i in range(size)
    )


def assert_matrices_close(
    actual: tuple[tuple[float, ...], ...],
    expected: tuple[tuple[float, ...], ...],
    tolerance: float,
) -> None:
    assert len(actual) == len(expected)
    for row, expected_row in zip(actual, expected, strict=True):
        assert row == pytest.approx(expected_row, abs=tolerance)


def test_line_of_sight_of_a_zenith_satellite_points_up() -> None:
    assert SatelliteGeometry(0.0, 90.0).line_of_sight() == pytest.approx(
        (0.0, 0.0, 1.0), abs=1e-12
    )
    assert SatelliteGeometry(90.0, 0.0).line_of_sight() == pytest.approx(
        (1.0, 0.0, 0.0), abs=1e-12
    )


def test_design_row_negates_the_line_of_sight() -> None:
    assert design_row(SatelliteGeometry(0.0, 90.0)) == pytest.approx(
        (0.0, 0.0, -1.0, 1.0), abs=1e-12
    )


def test_normal_matrix_of_the_documented_geometry_is_hand_computable() -> None:
    assert_matrices_close(
        normal_matrix(design_matrix(ZENITH_AND_HORIZON)), NORMAL_MATRIX, 1e-12
    )


def test_closed_form_dop_for_four_zenith_and_three_horizon_satellites() -> None:
    dop = DilutionOfPrecision.from_geometry(ZENITH_AND_HORIZON)
    assert dop.gdop == pytest.approx(math.sqrt(3.25), abs=1e-9)
    assert dop.pdop == pytest.approx(math.sqrt(2.75), abs=1e-9)
    assert dop.hdop == pytest.approx(math.sqrt(2.0), abs=1e-9)
    assert dop.vdop == pytest.approx(math.sqrt(0.75), abs=1e-9)
    assert dop.tdop == pytest.approx(math.sqrt(0.5), abs=1e-9)


def test_covariance_of_the_documented_geometry_is_hand_computable() -> None:
    covariance = (
        (1.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.0, 0.0),
        (0.5, 0.0, 0.75, 0.5),
        (0.5, 0.0, 0.5, 0.5),
    )
    assert_matrices_close(invert(NORMAL_MATRIX), covariance, 1e-12)


def test_inverse_is_a_two_sided_identity() -> None:
    inverse = invert(NORMAL_MATRIX)
    assert_matrices_close(product(NORMAL_MATRIX, inverse), IDENTITY, 1e-10)
    assert_matrices_close(product(inverse, NORMAL_MATRIX), IDENTITY, 1e-10)


def test_inverse_rejects_a_singular_matrix() -> None:
    with pytest.raises(ValueError):
        invert(((1.0, 2.0), (2.0, 4.0)))


def test_three_satellites_leave_the_geometry_singular() -> None:
    with pytest.raises(ValueError):
        DilutionOfPrecision.from_geometry(ZENITH_AND_HORIZON[:3])


def test_removing_a_satellite_never_lowers_pdop() -> None:
    satellites = geometry_from_records(frames(True))
    assert len(satellites) == 28
    full = DilutionOfPrecision.from_geometry(satellites)
    reduced = [
        DilutionOfPrecision.from_geometry(satellites[:index] + satellites[index + 1 :])
        for index in range(len(satellites))
    ]
    for dop in reduced:
        assert dop.pdop + 1e-12 >= full.pdop
    assert any(dop.pdop > full.pdop + 1e-3 for dop in reduced)


def test_dop_ordering_holds_for_the_captured_sky() -> None:
    dop = DilutionOfPrecision.from_geometry(geometry_from_records(frames(True)))
    assert all(
        math.isfinite(value)
        for value in (dop.gdop, dop.pdop, dop.hdop, dop.vdop, dop.tdop)
    )
    assert dop.hdop <= dop.pdop <= dop.gdop
    assert dop.vdop <= dop.pdop
    assert dop.tdop <= dop.gdop


def test_psrdop_fixture_matches_its_ascii_fields() -> None:
    path = FIXTURES / "captures" / "PSRDOPA.bin"
    request = FirmwareLog.PSRDOP.request()
    record = next(
        FirmwareLog.PSRDOP.decode(message)
        for message in StreamDecoder().feed(path.read_bytes())
        if request.matches(message)
    )
    line = next(
        row
        for row in path.read_text(encoding="ascii").splitlines()
        if row.startswith("#PSRDOPA")
    )
    reported = ReportedDilution.from_record(record, "PSRDOP")
    fields = [float(value) for value in line.split(";")[1].split(",")[:7]]
    assert reported.gdop == pytest.approx(fields[0], abs=1e-9)
    assert reported.pdop == pytest.approx(fields[1], abs=1e-9)
    assert reported.hdop == pytest.approx(fields[2], abs=1e-9)
    assert reported.tdop == pytest.approx(fields[4], abs=1e-9)
    assert reported.elevation_mask == pytest.approx(fields[5], abs=1e-9)
    assert reported.satellites == int(fields[6])
