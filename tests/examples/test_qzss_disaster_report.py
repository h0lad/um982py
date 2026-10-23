import json
from pathlib import Path

from examples.qzss_disaster_report.__main__ import main

from um982py.protocol.checksums import nmea_checksum


def test_manual_example_and_crc_failure(tmp_path: Path) -> None:
    wire = Path("tests/fixtures/qzqsm-example.nmea")
    output = tmp_path / "report.json"
    assert main(["--replay", str(wire), "--json", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["reports"][0]["category"] == "weather"
    assert report["reports"][0]["classification"] == "priority"
    assert report["reports"][0]["weather"]["regions"][0]["region_code"] == 471000

    body = wire.read_bytes().split(b"*")[0][1:]
    damaged = body[:28] + (b"1" if body[28:29] != b"1" else b"2") + body[29:]
    invalid = tmp_path / "corrupt.nmea"
    invalid.write_bytes(b"$" + damaged + f"*{nmea_checksum(damaged):02X}\r\n".encode())
    assert main(["--replay", str(invalid), "--json", str(output)]) == 1
    assert (
        json.loads(output.read_text())["rejected"][0]["error"] == "invalid L1S CRC-24Q"
    )
