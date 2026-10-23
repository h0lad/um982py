import json
from pathlib import Path
from struct import pack

from examples.research_session.base_rover import main

from tests.test_protocol import binary


def test_replay_keeps_base_and_rover_observations_and_timestamps(
    tmp_path: Path,
) -> None:
    status = 0x1C00
    observation = pack(
        "<HHddHHfHHfI", 0, 4, 20_000_000, -100_000_000, 0, 0, 0, 4500, 0, 1, status
    )
    payload = pack("<I", 1) + observation
    capture = tmp_path / "observations.bin"
    capture.write_bytes(binary(payload, 284) + binary(payload, 12))
    output = tmp_path / "paired.json"
    assert main(["--replay", str(capture), "--json", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["paired_epochs"] == 1
    row = result["epochs"][0]["signals"][0]
    assert row["identity"]["satellite"] == 4
    assert row["base"]["cn0_dbhz"] == 45
    assert row["base"]["adr_cycles_raw"] == -100_000_000
    assert row["base"]["tracking_status"] == status
