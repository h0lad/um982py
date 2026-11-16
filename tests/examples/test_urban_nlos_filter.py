"""Tests for urban_nlos_filter helpers."""

from __future__ import annotations

import pytest
from examples.urban_nlos_filter import classify_satellite, nlos_score

from um982py.satellites import Satellite, SatelliteSignal


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
