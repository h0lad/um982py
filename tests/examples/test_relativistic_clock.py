"""Checks the eccentricity clock term against its closed form and a replay."""

import json
import math
from pathlib import Path

import pytest
from examples.relativistic_clock import orbit_term, without_relativity
from examples.relativistic_clock.__main__ import main
from examples.wls_position import RangeMeasurement

from um982py.capture import load_records
from um982py.commands import Log
from um982py.experimental.orbit import KeplerElements, orbit_state
from um982py.gnss import MU, SPEED_OF_LIGHT
from um982py.messages.enums import SatelliteSystem

REPLAY = (
    Path(__file__).resolve().parents[1] / "fixtures" / "specialist"
) / "relativity-session.bin"
GPS = load_records(REPLAY, Log.GPSEPH)


def test_amplitude_matches_the_closed_form() -> None:
    record = GPS[0]
    term = orbit_term(record)
    elements = KeplerElements.from_record(record)
    expected = (
        2 * math.sqrt(MU * elements.semi_major_axis) * elements.eccentricity
    ) / SPEED_OF_LIGHT**2
    assert term.amplitude_ns == pytest.approx(expected * 1e9, rel=1e-12)
    assert term.amplitude_m == pytest.approx(expected * SPEED_OF_LIGHT, rel=1e-12)


def test_state_clock_carries_its_relativistic_part() -> None:
    elements = KeplerElements.from_record(GPS[0])
    state = orbit_state(elements, 1_000.0)
    polynomial = elements.af0 + elements.af1 * 1_000.0 - elements.tgd
    assert state.clock_bias - state.relativity == pytest.approx(polynomial, abs=1e-15)
    assert 0 < abs(state.relativity) < 50e-9


def test_dropping_the_term_changes_only_the_clock() -> None:
    measurement = RangeMeasurement(
        SatelliteSystem.GPS, 1, 1.0, 2.0, 3.0, 2e7, 1.0, 5e-6, 2e-8
    )
    (reduced,) = without_relativity([measurement])
    assert reduced.satellite_clock == pytest.approx(5e-6 - 2e-8)
    assert reduced.relativity == 0.0
    assert reduced.pseudorange == measurement.pseudorange


def test_replay_moves_the_position_by_metres(tmp_path: Path) -> None:
    report = tmp_path / "relativity.json"
    assert main(["--replay", str(REPLAY), "--json", str(report)]) == 0
    result = json.loads(report.read_text())
    shift = result["position_shift_without_relativity"]
    assert shift["epochs"] == 26
    assert 1.0 < shift["median_horizontal_m"] < 20.0
    assert {item["system"] for item in result["orbit_amplitudes"]} == {
        "GPS",
        "GALILEO",
        "BEIDOU",
    }
    assert "x" not in result and "latitude" not in json.dumps(result)
