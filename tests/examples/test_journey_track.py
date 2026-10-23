import json
from pathlib import Path

import pytest
from examples.journey_track import __main__ as journey

from test_bodies import EXAMPLES
from um982py.messages import Record


def position(epoch: float, east_mps: float, status: str = "SOL_COMPUTED") -> Record:
    return Record(
        "BESTNAVXYZ",
        tuple(
            {
                "epoch": epoch,
                "p_sol_status": status,
                "pos_type": "SINGLE",
                "p_x": 6378137.0,
                "p_y": 0.0,
                "p_z": 0.0,
                "v_sol_status": "SOL_COMPUTED",
                "vel_type": "DOPPLER_VELOCITY",
                "v_x": 3.0,
                "v_y": east_mps,
                "v_z": 0.0,
                "v_latency": 0.0,
            }.items()
        ),
    )


def test_motion_and_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journey, "record_epoch", lambda row: row.real("epoch"))
    result = journey.analyze(
        [
            position(1, 2),
            position(2, 4),
            position(10, 6),
            position(11, 2, "INSUFFICIENT_OBS"),
            position(12, 2),
        ],
        [],
        max_gap=2,
        moving_threshold=1,
        course_threshold=1,
        heading_tolerance=0.5,
        swapped=False,
    )
    assert result["integrated_ground_distance_m"] == 3
    assert result["covered_velocity_interval_s"] == 1
    assert result["moving_time_s"] == 1
    assert result["gaps_over_limit"] == 1
    assert result["rejected_position_epochs"] == 1
    samples = result["samples"]
    assert isinstance(samples, list)
    assert samples[0]["course_true_deg"] == 90
    assert samples[0]["vertical_speed_mps"] == 3


def test_manual_replay(tmp_path: Path) -> None:
    capture = tmp_path / "capture.txt"
    capture.write_text(EXAMPLES["BESTNAVXYZA"] + "\r\n")
    report = tmp_path / "report.json"
    assert (
        journey.main(
            ["--profile", "aviation", "--replay", str(capture), "--json", str(report)]
        )
        == 0
    )
    data = json.loads(report.read_text())
    assert data["profile"] == "aviation"
    assert len(data["samples"]) == 1
    assert data["integrated_ground_distance_m"] is None
    assert data["samples"][0]["course_true_deg"] is None


def test_waypoint_and_baseline_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journey, "record_epoch", lambda row: row.real("epoch"))
    baseline = Record(
        "BSLNENUHD",
        (
            ("epoch", 1.1),
            ("p_sol_status", "SOL_COMPUTED"),
            ("delta_1", 1.0),
            ("delta_2", 0.0),
            ("delta_3", 0.0),
        ),
    )
    result = journey.analyze(
        [position(1, 2)],
        [baseline],
        max_gap=2,
        moving_threshold=1,
        course_threshold=1,
        heading_tolerance=0.2,
        swapped=True,
        waypoint=(0, 1),
    )
    samples = result["samples"]
    assert isinstance(samples, list)
    sample = samples[0]
    assert sample["baseline_heading_true_deg"] == pytest.approx(270)
    assert sample["heading_epoch_offset_s"] == pytest.approx(0.1)
    assert sample["waypoint_bearing_true_deg"] == pytest.approx(90)
    assert sample["waypoint_closing_speed_mps"] == pytest.approx(2)
    assert sample["waypoint_distance_spherical_m"] == pytest.approx(111195, abs=1)


def test_rejects_overwriting_replay(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    capture.write_text("unchanged")
    with pytest.raises(SystemExit):
        journey.main(
            ["--profile", "sport", "--replay", str(capture), "--json", str(capture)]
        )
    assert capture.read_text() == "unchanged"
