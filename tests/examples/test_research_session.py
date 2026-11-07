import hashlib
import json
from pathlib import Path

from examples.research_session.__main__ import main

from test_bodies import EXAMPLES


def test_documented_observation_replay(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "fixtures/obsvm-example.txt"
    destination = tmp_path / "session"
    assert main(["--replay", str(source), "--output-dir", str(destination)]) == 0
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["capture_counts"]["OBSVM"] == 1
    assert manifest["artifacts"]["OBSVM"]["epochs"] == 1
    assert (destination / "primary.obs").is_file()
    assert "GPSEPH" not in manifest["artifacts"]


def test_replay_provenance_and_observations(tmp_path: Path) -> None:
    raw = tmp_path / "input.bin"
    raw.write_bytes(
        (EXAMPLES["OBSVMA"] + "\r\n" + EXAMPLES["GPSEPHA"] + "\r\n").encode()
    )
    destination = tmp_path / "out"
    assert main(["--replay", str(raw), "--output-dir", str(destination)]) == 0
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["capture_counts"]["OBSVM"] == 1
    assert (
        manifest["raw_capture"]["sha256"]
        == hashlib.sha256(raw.read_bytes()).hexdigest()
    )
    assert manifest["receiver_firmware"] is None
    assert manifest["provenance"]["schema"] == "um982py-provenance-1"
    assert manifest["provenance"]["coordinate_frame"] is None
    assert manifest["provenance"]["gap_detection_interval_seconds"] is None
    for name in ("OBSVM", "GPSEPH"):
        info = manifest["artifacts"][name]
        assert (
            hashlib.sha256((destination / info["path"]).read_bytes()).hexdigest()
            == info["sha256"]
        )
