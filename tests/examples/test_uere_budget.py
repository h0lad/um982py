"""Tests the UERE budget example."""

from __future__ import annotations

import math

import pytest
from examples.uere_budget import (
    UereEstimate,
    agreement_ratio,
    estimate_epoch,
    horizontal_sigma,
    median_uere,
    pseudorange_uere,
    vertical_dilution,
)

from um982py.messages import Record

PSRDOP_HDOP = 0.8035935163497925
PSRDOP_PDOP = 1.28986394405365
PSRDOP_HTDOP = 1.036347508430481
DERIVED_VDOP = 1.0089531478964784
SYNTHETIC_UERE = 2.5
SYNTHETIC_HDOP = 1.2
SYNTHETIC_VDOP = 1.7


def synthetic_epoch(uere: float, hdop: float, vdop: float) -> UereEstimate:
    axis_sigma = uere * hdop / math.sqrt(2)
    position = Record(
        "BESTPOS",
        (
            ("lat_std", axis_sigma),
            ("lon_std", axis_sigma),
            ("hgt_std", uere * vdop),
        ),
    )
    dilution = Record(
        "PSRDOP",
        (("hdop", hdop), ("pdop", math.hypot(hdop, vdop))),
    )
    return estimate_epoch(0, position, dilution)


def test_horizontal_sigma_combines_the_two_axis_sigmas() -> None:
    assert horizontal_sigma(3.0, 4.0) == pytest.approx(5.0, abs=1e-12)


def test_vertical_dilution_satisfies_the_pdop_identity() -> None:
    assert vertical_dilution(5.0, 3.0) == pytest.approx(4.0, abs=1e-12)


def test_vertical_dilution_of_the_capture_matches_the_derived_value() -> None:
    assert vertical_dilution(PSRDOP_PDOP, PSRDOP_HDOP) == pytest.approx(
        DERIVED_VDOP, abs=1e-5
    )


def test_vertical_dilution_tracks_htdop_without_being_the_same_field() -> None:
    vdop = vertical_dilution(PSRDOP_PDOP, PSRDOP_HDOP)
    assert vdop == pytest.approx(PSRDOP_HTDOP, abs=0.05)


def test_vertical_dilution_rejects_a_pdop_below_hdop() -> None:
    with pytest.raises(ValueError, match="PDOP"):
        vertical_dilution(0.5, 1.0)


def test_vertical_dilution_rejects_a_non_positive_dop() -> None:
    with pytest.raises(ValueError, match="positive"):
        vertical_dilution(0.0, 0.0)


def test_synthetic_sigma_is_recovered_exactly() -> None:
    estimate = synthetic_epoch(SYNTHETIC_UERE, SYNTHETIC_HDOP, SYNTHETIC_VDOP)
    assert estimate.hdop == pytest.approx(SYNTHETIC_HDOP, abs=1e-12)
    assert estimate.vdop == pytest.approx(SYNTHETIC_VDOP, abs=1e-12)
    assert estimate.horizontal_uere == pytest.approx(SYNTHETIC_UERE, rel=1e-12)
    assert estimate.vertical_uere == pytest.approx(SYNTHETIC_UERE, rel=1e-12)


def test_pseudorange_uere_rejects_an_empty_range_record() -> None:
    with pytest.raises(ValueError, match="observations"):
        pseudorange_uere(Record("RANGE", (("count", 0),)))


def test_agreement_ratio_rejects_a_non_positive_reference() -> None:
    with pytest.raises(ValueError, match="positive"):
        agreement_ratio(1.0, 0.0)


def test_median_uere_rejects_an_empty_series() -> None:
    with pytest.raises(ValueError, match="at least one epoch"):
        median_uere(())
