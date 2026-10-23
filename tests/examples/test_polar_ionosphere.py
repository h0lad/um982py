import json
from pathlib import Path

import pytest
from examples.polar_ionosphere.__main__ import main


def test_empty_capture_is_not_a_measurement(tmp_path: Path) -> None:
    capture = tmp_path / "empty.bin"
    capture.write_bytes(b"")
    report = tmp_path / "report.json"
    assert main(["--replay", str(capture), "--json", str(report)]) == 1
    assert json.loads(report.read_text())["status"] == "no_dual_frequency_gps"


def test_roti_coverage_and_missing_frequency_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examples.polar_ionosphere import __main__ as polar

    from um982py.messages import Record

    def observation(epoch: int, signal: int) -> Record:
        return Record(
            "OBS",
            (
                ("prn", 7),
                ("tracking_status", (signal << 21) | (1 << 12) | (1 << 10)),
                ("cn0", 40.0),
                ("pseudorange", 20_000_000.0 + (epoch * epoch if signal else 0)),
                ("carrier_phase", 1.0),
                ("lock_time", float(epoch + 1)),
            ),
        )

    records = tuple(
        Record(
            "RANGE",
            (
                ("epoch", float(epoch)),
                (
                    "observations",
                    (observation(epoch, 0),)
                    if epoch == 5
                    else (observation(epoch, 0), observation(epoch, 14)),
                ),
            ),
        )
        for epoch in range(11)
    )
    monkeypatch.setattr(polar, "record_epoch", lambda row: row.real("epoch"))
    monkeypatch.setattr(
        polar,
        "capture_records",
        lambda *args, **kwargs: {"RANGE": records, "BESTNAV": (), "JAMSTATUS": ()},
    )
    monkeypatch.setattr(polar, "audit_observations", lambda _: None)
    output = tmp_path / "report.json"
    assert (
        polar.main(
            ["--json", str(output), "--roti-window-s", "4", "--min-roti-samples", "3"]
        )
        == 0
    )
    timeline = {
        row["gps_seconds"]: row for row in json.loads(output.read_text())["timeline"]
    }
    assert timeline[3]["roti_window_coverage"] == 0.75
    assert timeline[3]["code_roti_tecu_per_min"] is None
    assert timeline[4]["roti_window_coverage"] == 1
    assert timeline[4]["code_roti_tecu_per_min"] is not None
    assert timeline[6]["code_rot_tecu_per_min"] is None
    assert timeline[6]["roti_rate_samples"] == 0
    assert timeline[9]["code_roti_tecu_per_min"] is None
    assert timeline[10]["code_roti_tecu_per_min"] is not None
    relaxed = tmp_path / "relaxed.json"
    assert (
        polar.main(
            [
                "--json",
                str(relaxed),
                "--roti-window-s",
                "4",
                "--min-roti-samples",
                "2",
                "--min-roti-coverage",
                "0.5",
            ]
        )
        == 0
    )
    relaxed_rows = {
        row["gps_seconds"]: row for row in json.loads(relaxed.read_text())["timeline"]
    }
    assert relaxed_rows[2]["roti_window_coverage"] == 0.5
    assert relaxed_rows[2]["code_roti_tecu_per_min"] is not None
    assert json.loads(relaxed.read_text())["min_roti_coverage"] == 0.5


def test_rejects_inadequate_roti_settings(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--json", str(tmp_path / "out.json"), "--min-roti-coverage", "0"])
    with pytest.raises(SystemExit):
        main(["--json", str(tmp_path / "out.json"), "--min-roti-samples", "1"])
