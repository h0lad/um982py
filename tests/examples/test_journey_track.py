import json
from pathlib import Path

import pytest
from examples.journey_track import __main__ as journey

from test_bodies import EXAMPLES
from um982py.messages import Record
from um982py.protocol.checksums import unicore_crc32


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
                "p_x_std": 1.0,
                "p_y_std": 2.0,
                "p_z_std": 3.0,
                "v_sol_status": "SOL_COMPUTED",
                "vel_type": "DOPPLER_VELOCITY",
                "v_x": 3.0,
                "v_y": east_mps,
                "v_z": 0.0,
                "v_latency": 0.0,
            }.items()
        ),
    )


def doppler(
    epoch: float,
    ground_speed: float,
    track: float = 90.0,
    vertical: float = 0.0,
    status: str = "SOL_COMPUTED",
    velocity_type: str = "DOPPLER_VELOCITY",
) -> Record:
    return Record(
        "DOPPVEL",
        (
            ("epoch", epoch),
            ("v_sol_status", status),
            ("vel_type", velocity_type),
            ("latency", 0.1),
            ("age", 0.2),
            ("hor_spd", ground_speed),
            ("trk_gnd", track),
            ("vert_spd", vertical),
            ("verspd_std", 0.3),
            ("horspd_std", 0.4),
        ),
    )


def test_doppler_supplies_speed_course_and_vertical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(journey, "gps_epoch", lambda row: row.real("epoch"))
    result = journey.analyze(
        [position(1, 2), position(2, 4)],
        doppler=[doppler(1.1, 10, vertical=2), doppler(2.1, 12, vertical=4)],
        max_gap=2,
        moving_threshold=1,
        course_threshold=1,
        heading_tolerance=0.5,
        swapped=False,
        doppler_tolerance=0.5,
    )
    assert result["velocity_sources"] == ["DOPPVEL"]
    assert result["matched_doppler_epochs"] == 2
    assert result["unmatched_doppler_epochs"] == 0
    assert result["integrated_ground_distance_m"] == 11
    first, second = result["samples"]
    assert first["velocity_source"] == "DOPPVEL"
    assert first["ground_speed_mps"] == 10
    assert first["course_true_deg"] == 90
    assert first["vertical_speed_mps"] == 2
    assert first["velocity_epoch_offset_s"] == pytest.approx(0.1)
    assert first["velocity_latency_s"] == 0.1
    assert first["ground_speed_standard_deviation_mps"] == 0.4
    assert second["ground_speed_mps"] == 12


def test_invalid_and_distant_doppler_reports_are_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(journey, "gps_epoch", lambda row: row.real("epoch"))
    result = journey.analyze(
        [position(1, 2)],
        [
            doppler(1, 20, status="INSUFFICIENT_OBS"),
            doppler(1, 21, velocity_type="NONE"),
            doppler(9, 22),
        ],
        max_gap=2,
        moving_threshold=1,
        course_threshold=1,
        heading_tolerance=0.5,
        swapped=False,
        doppler_tolerance=0.5,
    )
    assert result["matched_doppler_epochs"] == 0
    assert result["rejected_doppler_epochs"] == 2
    assert result["unmatched_doppler_epochs"] == 1
    sample = result["samples"][0]
    assert sample["velocity_source"] is None
    assert sample["ground_speed_mps"] is None


def test_manual_replay_uses_doppler_velocity_report(tmp_path: Path) -> None:
    body = (
        "DOPPVELA,91,GPS,FINE,2190,364674000,0,0,18,9;SOL_COMPUTED,"
        "DOPPLER_VELOCITY,0.000,0.000,10.000,90.000,2.000,0.100,0.200"
    )
    frame = f"#{body}*{unicore_crc32(body.encode()):08x}\r\n".encode()
    capture = tmp_path / "capture.bin"
    capture.write_bytes((EXAMPLES["BESTNAVXYZA"] + "\r\n").encode() + frame)
    report = tmp_path / "report.json"
    assert (
        journey.main(
            [
                "--profile",
                "marine",
                "--replay",
                str(capture),
                "--json",
                str(report),
            ]
        )
        == 0
    )
    data = json.loads(report.read_text())
    assert data["matched_doppler_epochs"] == 1
    sample = data["samples"][0]
    assert sample["velocity_source"] == "DOPPVEL"
    assert sample["ground_speed_mps"] == 10
    assert sample["ground_speed_kmh"] == 36


def test_motion_and_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journey, "gps_epoch", lambda row: row.real("epoch"))
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
    assert samples[0]["position_ecef_standard_deviation_m"] == [1.0, 2.0, 3.0]


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
    monkeypatch.setattr(journey, "gps_epoch", lambda row: row.real("epoch"))
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
