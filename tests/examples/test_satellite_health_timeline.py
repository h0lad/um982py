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


def test_live_satellite_ids_carry_the_prn_in_the_high_half() -> None:
    # R4.10Build25164 SATELLITEB, GLONASS, 2026-11-24: bytes 0-1 hold the
    # frequency channel and bytes 2-3 the slot + 37, matching SATVIS2.
    from um982py.commands import Log
    from um982py.protocol import StreamDecoder

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "crosscheck"
    message = next(
        iter(StreamDecoder().feed((fixture / "SATELLITEB-GLONASS.bin").read_bytes()))
    )
    record = Log.SATELLITE.decode(message)
    ids = [
        (row["prn_slot"].integer("prn"), row["prn_slot"].integer("channel"))
        for row in record.records("satellites")
    ]
    assert ids == [
        (44, 5),
        (45, 6),
        (50, -2),
        (51, -7),
        (52, 0),
        (54, 4),
        (60, 3),
        (61, 2),
    ]
