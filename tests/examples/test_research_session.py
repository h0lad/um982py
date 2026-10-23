import hashlib
import json
from pathlib import Path

from examples.research_session.__main__ import main

from test_bodies import EXAMPLES


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
    for name in ("OBSVM", "GPSEPH"):
        info = manifest["artifacts"][name]
        assert (
            hashlib.sha256((destination / info["path"]).read_bytes()).hexdigest()
            == info["sha256"]
        )
