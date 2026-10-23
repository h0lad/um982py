import json
from pathlib import Path
from struct import pack

from examples.rtk_quality.matched_solution import main

from tests.test_protocol import binary


def test_replay_reports_uninterpreted_satellite_values(tmp_path: Path) -> None:
    payload = (
        bytes(36) + pack("<I", 1) + pack("<HHIdIdId", 14, 0, 5, 648.5, 4, -3.5, 0, 0.0)
    )
    capture, output = tmp_path / "matched.bin", tmp_path / "matched.json"
    capture.write_bytes(binary(payload, 2020))
    assert main(["--replay", str(capture), "--json", str(output)]) == 0
    result = json.loads(output.read_text())
    sat = result["epochs"][0]["satellites"][0]
    assert sat["satellite_id"] == 14
    assert sat["status_codes"] == [5, 4, 0]
    assert sat["values"] == [648.5, -3.5, 0.0]
    assert not result["status_transitions"]
