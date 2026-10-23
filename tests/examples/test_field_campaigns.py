import hashlib
import json
import math
from pathlib import Path

import pytest
from examples.doppler_velocity import wave_spectrum
from examples.doppler_velocity.wave_buoy import main as waves
from examples.gnss_reflectometry.water_level import main as water
from examples.polar_ionosphere.campaign import main as ionosphere
from examples.rtk_quality.compare_campaigns import main as quality
from examples.unattended_station.health_report import main as station
from examples.vadase.event_replay import main as event


def test_coastal_water_with_gauge_and_rejected_arc(tmp_path: Path) -> None:
    arcs = tmp_path / "arcs.csv"
    arcs.write_text(
        "antenna,system,prn,signal,direction,start_gps_s,end_gps_s,height_m,rejection\n"
        "ANT1,0,1,0,rising,100,200,1.5,\n"
        "ANT1,0,2,0,rising,100,200,,low_snr\n"
        "ANT1,0,3,0,rising,100,200,1.5,\n"
    )
    gauge = tmp_path / "gauge.csv"
    gauge.write_text("gps_seconds,water_level_m\n151,2.4\n")
    out = tmp_path / "water.json"
    assert (
        water(
            [
                "--arcs",
                str(arcs),
                "--antenna",
                "ANT1",
                "--antenna-elevation-m",
                "4",
                "--datum",
                "test datum",
                "--gauge",
                str(gauge),
                "--match-window-s",
                "5",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text())
    assert data["accepted_arcs"][0]["water_level_m"] == 2.5
    assert data["mean_difference_m"] == pytest.approx(0.1)
    assert data["unique_matched_gauge_epochs"] == 1
    assert data["reused_gauge_matches"] == 1
    assert data["accepted_arcs"][0]["gauge_time_difference_s"] == -1
    assert data["rejected_arcs"][0]["rejection"] == "low_snr"


def test_water_reference_requires_tolerance_and_unique_times(tmp_path: Path) -> None:
    arcs, gauge, out = (
        tmp_path / name for name in ("arcs.csv", "gauge.csv", "out.json")
    )
    arcs.write_text(
        "antenna,system,prn,signal,direction,start_gps_s,end_gps_s,height_m,rejection\n"
    )
    gauge.write_text("gps_seconds,water_level_m\n1,2\n1,3\n")
    args = [
        "--arcs",
        str(arcs),
        "--antenna",
        "ANT1",
        "--antenna-elevation-m",
        "4",
        "--datum",
        "test",
        "--gauge",
        str(gauge),
        "--output",
        str(out),
    ]
    with pytest.raises(SystemExit):
        water(args)
    with pytest.raises(ValueError, match="unique"):
        water([*args, "--match-window-s", "1"])


def test_station_health_checks_hash_and_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "station"
    seg = root / "segment-000001"
    seg.mkdir(parents=True)
    artifact = seg / "primary.obs"
    artifact.write_text("real observations")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (seg / "manifest.json").write_text(
        json.dumps(
            {
                "capture_counts": {"OBSVM": 5},
                "artifacts": {"OBSVM": {"path": "primary.obs", "sha256": digest}},
            }
        )
    )
    events = [
        {
            "segment": "segment-000001",
            "status": "started",
            "started_utc": "2026-01-01T00:00:00+00:00",
        },
        {
            "segment": "segment-000001",
            "status": "complete",
            "finished_utc": "2026-01-01T00:01:00+00:00",
        },
        {
            "segment": "segment-000002",
            "status": "started",
            "started_utc": "2026-01-01T00:02:00+00:00",
        },
    ]
    (root / "station.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events)
    )
    out = tmp_path / "health.json"
    markdown = tmp_path / "health.md"
    assert (
        station(
            [
                "--directory",
                str(root),
                "--output",
                str(out),
                "--markdown",
                str(markdown),
            ]
        )
        == 0
    )
    assert "1 verified" in markdown.read_text()
    assert "segment-000002 | incomplete" in markdown.read_text()
    data = json.loads(out.read_text())
    assert data["segments"][0]["artifacts"][0]["matches"] is True
    assert data["segments"][1]["status"] == "incomplete"
    assert data["between_segments"][0]["host_elapsed_s"] == 60
    artifact.write_text("changed")
    station(["--directory", str(root), "--output", str(out)])
    assert (
        json.loads(out.read_text())["segments"][0]["artifacts"][0]["matches"] is False
    )


def test_quality_campaigns_and_environment_labels(tmp_path: Path) -> None:
    report = tmp_path / "quality.json"
    rows = [
        {
            "epoch": t,
            "fix_class": c,
            "available": True,
            "fresh_fixed": c == "fixed",
            "differential_age": 1.0,
        }
        for t, c in [(100, "single"), (101, "fixed"), (110, "fixed")]
    ]
    report.write_text(json.dumps({"epochs": rows}))
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "start_gps_seconds,end_gps_seconds,environment\n100,102,open\n102,111,forest\n"
    )
    truth = tmp_path / "truth.csv"
    truth.write_text("gps_seconds,error_m\n101,2\n")
    out = tmp_path / "campaign.json"
    assert (
        quality(
            [
                "--campaign",
                "test",
                str(report),
                "--labels",
                str(labels),
                "--truth-error",
                str(truth),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    campaign = json.loads(out.read_text())["campaigns"][0]
    by_name = {entry["environment"]: entry for entry in campaign["environments"]}
    assert by_name["open"]["computed_fraction"] == 1
    assert by_name["open"]["matched_truth_samples"] == 1
    assert by_name["open"]["rms_position_error_m"] == 2
    assert campaign["gaps_over_limit"] == [
        {"start_gps_seconds": 101, "end_gps_seconds": 110}
    ]


def test_event_windows_require_observed_samples(tmp_path: Path) -> None:
    report = tmp_path / "polar.json"
    report.write_text(
        json.dumps(
            {
                "signals_hz": [1, 2],
                "timeline": [
                    {
                        "gps_seconds": 105,
                        "prn": 7,
                        "code_roti_tecu_per_min": 0.2,
                        "cn0_high_dbhz": 40,
                        "cn0_low_dbhz": 30,
                    }
                ],
            }
        )
    )
    events = tmp_path / "events.csv"
    events.write_text(
        "start_gps_seconds,end_gps_seconds,event\n100,110,storm\n110,120,quiet\n"
    )
    out = tmp_path / "polar-report.json"
    assert (
        ionosphere(
            [
                "--report",
                "station-a",
                str(report),
                "--events",
                str(events),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    windows = json.loads(out.read_text())["stations"][0]["event_windows"]
    assert windows[0]["dual_frequency_samples"] == 1
    assert windows[0]["median_cn0_dbhz_both_signals"] == 35
    assert windows[1]["median_code_roti_tecu_per_min"] is None


def test_wave_windows_do_not_bridge_gaps(tmp_path: Path) -> None:
    path = tmp_path / "velocity.csv"
    lines = ["gps_seconds,vertical_velocity_mps\n"]
    lines.extend(f"{i},{math.cos(2 * math.pi * i / 8)}\n" for i in range(16))
    lines.extend(f"{i + 10},{math.cos(2 * math.pi * i / 8)}\n" for i in range(16, 32))
    path.write_text("".join(lines))
    out = tmp_path / "waves.json"
    assert (
        waves(
            [
                "--input",
                str(path),
                "--interval-s",
                "1",
                "--window-samples",
                "16",
                "--min-frequency-hz",
                "0.1",
                "--max-frequency-hz",
                "0.5",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    result = json.loads(out.read_text())
    assert len(result["windows"]) == 2
    assert result["gap_count"] == 1
    assert result["windows"][0]["peak_period_s"] == pytest.approx(8)


def test_nyquist_is_not_doubled() -> None:
    count = 16
    samples = [(-1.0) ** i for i in range(count)]
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (count - 1)) for i in range(count)]
    expected = sum(window) ** 2 / sum(w * w for w in window) / math.pi**2
    assert wave_spectrum(samples, 1)[-1][1] == pytest.approx(expected)


def test_unavailable_intervals_are_censored_at_gaps(tmp_path: Path) -> None:
    report = tmp_path / "quality.json"
    rows = [
        {
            "epoch": t,
            "fix_class": "none" if not available else "single",
            "available": available,
            "fresh_fixed": False,
            "differential_age": 0,
        }
        for t, available in ((1, False), (2, False), (3, True), (4, False), (10, True))
    ]
    report.write_text(json.dumps({"epochs": rows}))
    out = tmp_path / "out.json"
    assert quality(["--campaign", "test", str(report), "--output", str(out)]) == 0
    intervals = json.loads(out.read_text())["campaigns"][0][
        "observed_unavailability_intervals"
    ]
    assert intervals[0]["observed_interval_s"] == 2
    assert intervals[0]["censored"] is False
    assert intervals[1]["censored"] is True
    assert intervals[1]["recovered_gps_seconds"] is None


def test_event_window_with_no_samples_is_not_success(tmp_path: Path) -> None:
    report, events, out = (tmp_path / p for p in ("r.json", "e.csv", "out.json"))
    report.write_text(json.dumps({"timeline": []}))
    events.write_text("start_gps_seconds,end_gps_seconds,event\n1,2,storm\n")
    assert (
        ionosphere(
            [
                "--report",
                "station",
                str(report),
                "--events",
                str(events),
                "--output",
                str(out),
            ]
        )
        == 1
    )
    window = json.loads(out.read_text())["stations"][0]["event_windows"][0]
    assert window["dual_frequency_samples"] == 0


def test_nearest_epoch_prefers_earlier_tie() -> None:
    from um982py.field_data import nearest_epoch

    assert nearest_epoch([(1.0, "a"), (3.0, "b")], [1.0, 3.0], 2.0) == (1.0, "a")
    assert nearest_epoch([], [], 2.0) is None


def test_unmatched_tdcp_reflects_actual_pairing(tmp_path: Path) -> None:
    doppler, tdcp, output = (
        tmp_path / name for name in ("dop.json", "tdcp.json", "out.json")
    )
    doppler.write_text(json.dumps({"epochs": [{"epoch": 10, "velocity": [0, 0, 0]}]}))
    tdcp.write_text(
        json.dumps(
            {
                "epochs": [
                    {
                        "epoch": 9.9,
                        "start_epoch": 9,
                        "velocity_mps": [0, 0, 0],
                        "displacement_m": [0, 0, 0],
                    },
                    {
                        "epoch": 10.1,
                        "start_epoch": 9.9,
                        "velocity_mps": [0, 0, 0],
                        "displacement_m": [0, 0, 0],
                    },
                ]
            }
        )
    )
    assert (
        event(
            [
                "--doppler",
                str(doppler),
                "--tdcp",
                str(tdcp),
                "--reference-frame",
                "test",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text())
    assert report["timeline"][0]["tdcp_end_gps_seconds"] == 9.9
    assert report["unmatched_tdcp_epochs"] == [10.1]


def test_event_combines_real_motion_reports(tmp_path: Path) -> None:
    from examples.doppler_velocity.__main__ import main as doppler
    from examples.vadase.__main__ import main as tdcp

    capture = Path("tests/fixtures/specialist/rtklib-motion.bin")
    first, second, out = (
        tmp_path / name for name in ("doppler.json", "tdcp.json", "event.json")
    )
    assert doppler(["--replay", str(capture), "--json", str(first)]) == 0
    assert tdcp(["--replay", str(capture), "--json", str(second)]) == 0
    assert (
        event(
            [
                "--doppler",
                str(first),
                "--tdcp",
                str(second),
                "--reference-frame",
                "synthetic ECEF",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text())
    assert len(data["timeline"]) == 16
    assert data["timeline"][0]["tdcp_velocity_ecef_mps"] is None
    assert (
        data["timeline"][1]["tdcp_start_gps_seconds"]
        < data["timeline"][1]["tdcp_end_gps_seconds"]
    )
