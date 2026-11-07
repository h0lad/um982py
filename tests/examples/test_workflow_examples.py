import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from examples.crs_transform import __main__ as crs_cli
from examples.field_recording import __main__ as recording_cli
from examples.live_position import __main__ as position_cli
from examples.ntrip_sources import __main__ as sources_cli
from examples.postprocessed_rtk import __main__ as ppk_cli

from conftest import sentence
from um982py.live import PositionUpdate
from um982py.messages.navigation import Fix
from um982py.ntrip import parse_sourcetable
from um982py.ppk import PpkResult
from um982py.session import SessionRecorder


def test_crs_example_transforms_coordinates(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("pyproj")
    assert crs_cli.main(["EPSG:4979", "EPSG:4978", "0", "0", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["x"] == pytest.approx(6378137)


def test_field_recording_example_replays_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "session"
    with SessionRecorder(directory, metadata={}, segment_bytes=5) as recorder:
        recorder.write(sentence(b"GPGGA,1"))
    assert recording_cli.main(["replay", str(directory)]) == 0
    assert "GPGGA" in capsys.readouterr().out


def test_live_example_outputs_geojson(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Session:
        def positions(self, stop: object) -> object:
            del stop
            fix = Fix("120000", 50, 8, 1, 10, 1, 100, 45, 1, "base")
            yield PositionUpdate(fix, datetime(2020, 1, 1, tzinfo=UTC), 1, None, 1)

    monkeypatch.setattr(position_cli, "PositionSession", lambda *a, **k: Session())
    assert position_cli.main(["/dev/test", "--geojson"]) == 0
    assert json.loads(capsys.readouterr().out)["geometry"]["coordinates"] == [
        8,
        50,
        145,
    ]


def test_ntrip_sources_example_orders_by_distance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    table = (
        "STR;FAR;far;RTCM;;2;GPS;net;DEU;51;8;0;0;receiver;none;N;N;0;\n"
        "STR;NEAR;near;RTCM;;2;GPS;net;DEU;50;8;0;0;receiver;none;N;N;0;\n"
    )
    monkeypatch.setattr(
        sources_cli, "fetch_sourcetable", lambda *a, **k: parse_sourcetable(table)
    )
    assert sources_cli.main(["http://caster.test", "--position", "50", "8"]) == 0
    assert [item["name"] for item in json.loads(capsys.readouterr().out)] == [
        "NEAR",
        "FAR",
    ]


def test_ppk_example_passes_reference_metadata(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = {}

    def process(*args: object, **kwargs: object) -> PpkResult:
        called.update(kwargs)
        return PpkResult(Path("solution.pos"), Path("run.json"), 1, ((1, 1),))

    monkeypatch.setattr(ppk_cli, "run_ppk", process)
    assert (
        ppk_cli.main(
            [
                "rover.obs",
                "base.obs",
                "nav.nav",
                "--output",
                "result",
                "--base-ecef",
                "6378137",
                "0",
                "0",
                "--reference-frame",
                "test",
            ]
        )
        == 0
    )
    assert (
        called["base_ecef"] == (6378137, 0, 0) and called["reference_frame"] == "test"
    )
    assert "1 solutions" in capsys.readouterr().out
