"""Exercise the RTKDATA engine-state example on synthetic frames."""

import json
from pathlib import Path
from struct import pack

import pytest
from examples.rtk_quality.engine_state import main

from tests.test_protocol import binary

_COVARIANCE = (45.801, 2.914, 9.572, 2.914, 44.613, -18.225, 9.572, -18.225, 111.597)


def _rtk_data_payload(
    entries: tuple[tuple[int, int, int], ...],
    covariance: tuple[float, ...] = _COVARIANCE,
) -> bytes:
    """Frame synthetic engine entries behind a zero header and covariance."""
    header = bytearray(108)
    header[28:64] = pack("<9f", *covariance)
    return bytes(header) + b"".join(pack("<III", *entry) for entry in entries)


def test_replay_reports_covariance_and_resolved_satellites(
    tmp_path: Path,
) -> None:
    capture, output = tmp_path / "engine.bin", tmp_path / "engine.json"
    capture.write_bytes(
        binary(_rtk_data_payload(((10, 5, 0), (250, 70, 0))), 215)
        + binary(_rtk_data_payload(((78, 15, 0),)), 2027)
    )
    assert main(["--replay", str(capture), "--json", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["status"] == "ok"
    first, second = result["epochs"]
    assert first["report"] == "RTKDATA"
    assert first["variances"] == pytest.approx([45.801, 44.613, 111.597])
    assert [(sat["system"], sat["prn"]) for sat in first["satellites"]] == [
        ("GPS", 10),
        (None, None),
    ]
    assert [sat["status"] for sat in first["satellites"]] == [5, 70]
    assert second["report"] == "RTKDATA2"
    assert [(sat["system"], sat["prn"]) for sat in second["satellites"]] == [
        ("GALILEO", 4)
    ]


def test_empty_replay_reports_insufficient_data(tmp_path: Path) -> None:
    capture, output = tmp_path / "empty.bin", tmp_path / "empty.json"
    capture.write_bytes(b"")
    assert main(["--replay", str(capture), "--json", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "insufficient_data"


def test_heading_replay_reports_reference_satellite(tmp_path: Path) -> None:
    capture, output = tmp_path / "heading.bin", tmp_path / "heading.json"
    data = bytearray(_rtk_data_payload(((10, 70, 0),)))
    data[0:8] = pack("<II", 0, 34)
    data[104:108] = pack("<I", 1)
    capture.write_bytes(binary(_rtk_data_payload(()), 215) + binary(bytes(data), 6007))
    assert main(["--heading", "--replay", str(capture), "--json", str(output)]) == 0
    (epoch,) = json.loads(output.read_text())["epochs"]
    assert epoch["report"] == "RTKDATAH"
    assert epoch["covariance"] == pytest.approx(_COVARIANCE)
    assert epoch["position_type"] == 34
    assert epoch["satellites"][0]["status_label"] == "REFERENCE"
    assert epoch["satellites"][0]["ambiguity_fixed"] is None
