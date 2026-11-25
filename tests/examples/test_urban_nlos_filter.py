"""Tests for urban_nlos_filter helpers."""

import pytest
from examples.urban_nlos_filter import classify_satellite, evaluate_labelled, nlos_score

from um982py.satellites import Satellite, SatelliteSignal


def test_labelled_evaluation_keeps_unsure_cases() -> None:
    report = evaluate_labelled(
        [(90, 60, "LOS"), (0, 0, "NLOS"), (30, 35, "LOS")], 0.2, 0.8
    )
    assert report["samples"] == 3
    assert report["counts_by_truth_and_prediction"] == {
        "LOS": {"LOS": 1, "unsure": 1, "NLOS": 0},
        "NLOS": {"LOS": 0, "unsure": 0, "NLOS": 1},
    }


def test_nlos_score_extremes() -> None:
    assert nlos_score(90, 60) == pytest.approx(0.0, abs=1e-12)
    assert nlos_score(0, 0) == pytest.approx(1.0, abs=1e-12)


def test_nlos_score_increases_for_low_elevation() -> None:
    high = nlos_score(80, 45)
    low = nlos_score(10, 45)
    assert low > high


def test_classify_satellite_labels() -> None:
    sat = Satellite(
        prn=1,
        azimuth_deg=0,
        elevation_deg=10,
        signals=(SatelliteSignal(system_id=0, signal_id=0, snr=30),),
    )
    candidates = classify_satellite(sat)
    assert len(candidates) == 1
    assert candidates[0].label in ("unsure", "NLOS")
