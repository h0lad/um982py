import json
from pathlib import Path

from examples.satellite_health_timeline.__main__ import main


def test_gps_capture_reports_native_health(tmp_path: Path) -> None:
    output = tmp_path / "health.json"
    assert (
        main(["--replay", "tests/fixtures/captures/GPSEPHA.bin", "--json", str(output)])
        == 0
    )
    report = json.loads(output.read_text())
    assert report["events"]
    assert all(
        event["source"] == "GPSEPH" and event["system"] == "GPS"
        for event in report["events"]
    )
    assert "unknown" in report["limitations"]
