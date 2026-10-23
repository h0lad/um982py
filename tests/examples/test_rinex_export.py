from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from examples.rinex_export.__main__ import main

from tests.examples._new_api import observation, wire


def test_replay_exports_all_epochs_unless_limited(tmp_path: Path) -> None:
    replay = tmp_path / "capture.bin"
    replay.write_bytes(b"".join(wire(i, [observation()]) for i in range(65)))
    output, report = tmp_path / "all.obs", tmp_path / "report.json"
    assert (
        main(["--replay", str(replay), "--output", str(output), "--json", str(report)])
        == 0
    )
    assert json.loads(report.read_text())["files"][0]["epochs"] == 65
    assert output.read_text().count("\n> ") == 65
    limited = tmp_path / "limited.obs"
    assert (
        main(["--replay", str(replay), "--output", str(limited), "--frames", "3"]) == 0
    )
    assert limited.read_text().count("\n> ") == 3


def test_cli_metadata_per_antenna(tmp_path: Path) -> None:
    replay = tmp_path / "capture.bin"
    replay.write_bytes(
        wire(0, [observation()]) + wire(0, [observation()], secondary=True)
    )
    primary_metadata, secondary_metadata = (
        tmp_path / "primary.json",
        tmp_path / "secondary.json",
    )
    primary_metadata.write_text(
        json.dumps({"antenna_type": "PRIMARY", "antenna_delta_hen": [1, 0, 0]})
    )
    secondary_metadata.write_text(
        json.dumps({"antenna_type": "SECONDARY", "antenna_delta_hen": [2, 0, 0]})
    )
    output, other = tmp_path / "master.obs", tmp_path / "slave.obs"
    assert (
        main(
            [
                "--replay",
                str(replay),
                "--secondary",
                "--output",
                str(output),
                "--secondary-output",
                str(other),
                "--metadata",
                str(primary_metadata),
                "--secondary-metadata",
                str(secondary_metadata),
            ]
        )
        == 0
    )
    assert "PRIMARY" in output.read_text() and "SECONDARY" not in output.read_text()
    assert "SECONDARY" in other.read_text() and "PRIMARY" not in other.read_text()


def test_cli_replays_documented_obsv(tmp_path: Path) -> None:
    from test_bodies import EXAMPLES

    replay, output, report = (
        tmp_path / "capture.bin",
        tmp_path / "out.obs",
        tmp_path / "report.json",
    )
    replay.write_bytes((EXAMPLES["OBSVMA"] + "\r\n").encode())
    assert (
        main(
            [
                "--replay",
                str(replay),
                "--source",
                "obsv",
                "--output",
                str(output),
                "--json",
                str(report),
            ]
        )
        == 0
    )
    payload = json.loads(report.read_text())
    assert payload["files"][0]["input_log"] == "OBSVM"
    assert payload["files"][0]["observation_quality"]["epochs"] == 1
    assert "G26" in output.read_text()


def test_cli_exports_multignss_shared_epochs_and_omission_report(
    tmp_path: Path,
) -> None:
    replay = tmp_path / "capture.bin"
    first = wire(
        0,
        [observation(), observation(prn=7, system=3, signal=22)],
    )
    later = wire(1, [observation()])
    second = wire(0, [observation(cn0=41)], secondary=True)
    replay.write_bytes(first + later + second)
    master, slave, report = (
        tmp_path / "master.obs",
        tmp_path / "slave.obs",
        tmp_path / "report.json",
    )
    assert (
        main(
            [
                "--replay",
                str(replay),
                "--secondary",
                "--output",
                str(master),
                "--secondary-output",
                str(slave),
                "--json",
                str(report),
            ]
        )
        == 0
    )
    master_text, slave_text = master.read_text(), slave.read_text()
    assert "3.05" in master_text.splitlines()[0]
    assert "C6C" in master_text and "E07" in master_text and "G01" in master_text
    assert master_text.count("\n> ") == slave_text.count("\n> ") == 1
    assert "UM982" in master_text and "UM982-SLAVE" in slave_text
    result = json.loads(report.read_text())
    assert result["format"] == "RINEX 3.05"
    assert [item["epochs"] for item in result["files"]] == [1, 1]
    assert result["files"][0]["signal_observations"] == 2
    assert result["provenance"]["input_mode"] == "replay"
    assert (
        result["provenance"]["input_capture"]["sha256"]
        == hashlib.sha256(replay.read_bytes()).hexdigest()
    )
    assert result["provenance"]["capture_counts"] == {"RANGE": 2, "RANGEH": 1}
    assert result["provenance"]["receiver_configuration"] is None
    assert (
        result["files"][0]["sha256"] == hashlib.sha256(master.read_bytes()).hexdigest()
    )
    assert result["files"][0]["time_scale"] == "GPST"
    assert (
        result["files"][0]["first_epoch_gps_seconds"]
        == result["files"][0]["last_epoch_gps_seconds"]
    )


def test_cli_reports_unverified_l2c_and_accepts_explicit_component(
    tmp_path: Path,
) -> None:
    replay = tmp_path / "capture.bin"
    replay.write_bytes(
        wire(
            0,
            [
                observation(),
                observation(signal=9, l2c=1, frequency=1227.60e6),
            ],
        )
    )
    output, report = tmp_path / "observations.obs", tmp_path / "report.json"
    assert (
        main(["--replay", str(replay), "--output", str(output), "--json", str(report)])
        == 0
    )
    assert "C2S" not in output.read_text()
    assert json.loads(report.read_text())["files"][0]["omitted"] == {
        "unverified_l2c_component": 1
    }
    assert (
        main(
            [
                "--replay",
                str(replay),
                "--output",
                str(output),
                "--l2c-code",
                "2S",
            ]
        )
        == 0
    )
    assert "C2S" in output.read_text()
    assert "Type-9 L2C attribute supplied by caller" in output.read_text()


def test_cli_rejects_unshared_epochs_without_writing_files(tmp_path: Path) -> None:
    replay = tmp_path / "capture.bin"
    replay.write_bytes(
        wire(0, [observation()]) + wire(1, [observation()], secondary=True)
    )
    output = tmp_path / "master.obs"
    with pytest.raises(SystemExit, match="2"):
        main(["--replay", str(replay), "--secondary", "--output", str(output)])
    assert not output.exists()


def test_cli_rejects_input_or_output_path_collision(tmp_path: Path) -> None:
    replay = tmp_path / "capture.bin"
    replay.write_bytes(wire(0, [observation()]))
    with pytest.raises(SystemExit, match="2"):
        main(["--replay", str(replay), "--output", str(replay)])
    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "--replay",
                str(replay),
                "--secondary",
                "--output",
                str(tmp_path / "both.obs"),
                "--secondary-output",
                str(tmp_path / "both.obs"),
            ]
        )
    assert replay.read_bytes().startswith(b"\xaa\x44")
