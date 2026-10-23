import json
from pathlib import Path

import pytest
from examples.unattended_station import __main__ as station
from examples.unattended_station.__main__ import main

from test_bodies import EXAMPLES


def test_replay_resume_and_journal(tmp_path: Path) -> None:
    raw = tmp_path / "capture.bin"
    raw.write_bytes((EXAMPLES["OBSVMA"] + "\r\n").encode())
    root = tmp_path / "station"
    arguments = ["--replay", str(raw), "--directory", str(root), "--min-free-mib", "0"]
    assert main(arguments) == 0
    assert main(arguments) == 0
    events = [
        json.loads(line) for line in (root / "station.jsonl").read_text().splitlines()
    ]
    assert [event["segment"] for event in events if event["status"] == "complete"] == [
        "segment-000001",
        "segment-000002",
    ]
    assert [event["status"] for event in events] == [
        "started",
        "complete",
        "started",
        "complete",
    ]
    assert (root / "segment-000001/primary.obs").is_file()
    assert (root / "segment-000002/manifest.json").is_file()


def test_disk_limit_prevents_capture(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="disk"):
        main(["--directory", str(tmp_path), "--min-free-mib", "1e30"])


def test_retry_preserves_failed_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = iter((1, 0))
    monkeypatch.setattr(station, "record_session", lambda _: next(results))
    monkeypatch.setattr(station, "_snapshot", lambda _: None)
    monkeypatch.setattr(station.time, "sleep", lambda _: None)
    assert (
        main(
            [
                "--directory",
                str(tmp_path),
                "--min-free-mib",
                "0",
                "--retry-seconds",
                "1",
            ]
        )
        == 0
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "station.jsonl").read_text().splitlines()
    ]
    assert [event["status"] for event in events] == [
        "started",
        "failed",
        "started",
        "complete",
    ]
    assert (tmp_path / "segment-000001").is_dir()
    assert (tmp_path / "segment-000002").is_dir()
