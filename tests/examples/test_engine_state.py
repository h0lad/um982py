"""Exercise the RTKDATA engine-state example on synthetic frames."""

import json
from pathlib import Path
from struct import pack

import pytest
from examples.rtk_quality.engine_state import main

from tests.test_protocol import binary

_COVARIANCE = (45.801, 2.914, 9.572, 2.914, 44.613, -18.225, 9.572, -18.225, 111.597)


def _payload(
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
    """Synthetic RTKDATA and RTKDATA2 frames decode with system identities."""
    capture, output = tmp_path / "engine.bin", tmp_path / "engine.json"
    capture.write_bytes(
        binary(_payload(((10, 5, 0), (250, 70, 0))), 215)
        + binary(_payload(((78, 15, 0),)), 2027)
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
    """A capture without engine frames exits nonzero with a status marker."""
    capture, output = tmp_path / "empty.bin", tmp_path / "empty.json"
    capture.write_bytes(b"")
    assert main(["--replay", str(capture), "--json", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "insufficient_data"
