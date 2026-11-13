import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from examples.crs_transform import __main__ as crs_cli
from examples.field_recording import __main__ as recording_cli
from examples.live_position import __main__ as position_cli
from examples.ntrip_sources import __main__ as sources_cli
from examples.postprocessed_rtk import __main__ as ppk_cli

from conftest import ReplayTransport, sentence
from um982py.errors import TransportClosed
from um982py.live import PositionSession, PositionUpdate
from um982py.messages.navigation import Fix
from um982py.ntrip import ReconnectPolicy, parse_sourcetable
from um982py.ppk import PpkResult
from um982py.receiver import Receiver
from um982py.session import SessionGap, SessionRecorder, iter_session_events


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


def test_field_recording_example_reconnects_and_records_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks = []

    class Timer:
        def __init__(self, duration: float, callback: object) -> None:
            callbacks.append(callback)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

        def join(self) -> None:
            pass

    class Source(ReplayTransport):
        def __init__(self, *, final: bool) -> None:
            super().__init__(chunk=65536)
            self.final = final
            self.pending.extend(
                sentence(
                    b"GPGGA,123519,4807.038,N,01131.000,E,4,08,0.9,545.4,M,46.9,M,1.2,0001"
                )
            )

        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                raise TransportClosed("disconnected")
            data = super().read(size, timeout)
            if self.final:
                callbacks[0]()
            return data

    connections = iter((Source(final=False), Source(final=True)))
    monkeypatch.setattr(recording_cli, "Timer", Timer)
    monkeypatch.setattr(
        recording_cli.Receiver, "connect", lambda *args: Receiver(next(connections))
    )
    monkeypatch.setattr(
        recording_cli,
        "PositionSession",
        lambda factory, on_disconnect: PositionSession(
            factory,
            on_disconnect=on_disconnect,
            reconnect=ReconnectPolicy(0.001, 0.001),
        ),
    )
    directory = tmp_path / "field"
    assert recording_cli.main(["record", "/dev/test", str(directory)]) == 0
    events = list(iter_session_events(directory))
    assert len(events) == 3 and isinstance(events[1], SessionGap)


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


def test_live_example_reports_health_changes_without_another_fix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    monitor = Mock()
    monitor.status.side_effect = [
        SimpleNamespace(reasons=("position_stale",)),
        SimpleNamespace(reasons=("position_stale",)),
        SimpleNamespace(reasons=()),
    ]
    stop = Mock()
    stop.wait.side_effect = [False, False, False, True]
    position_cli.report_status(monitor, stop)
    assert capsys.readouterr().err.splitlines() == [
        "position health: position_stale",
        "position health: recovered",
    ]


def test_live_example_configures_requested_receiver_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []

    class Session:
        def __init__(self, factory: object, *, configure: object) -> None:
            from unittest.mock import Mock

            receiver = Mock()
            configure(receiver)  # type: ignore[operator]
            commands.extend(
                call.args[0].text for call in receiver.execute.call_args_list
            )

        def positions(self, stop: object) -> object:
            yield from ()

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    assert position_cli.main(["/dev/test", "--rate-hz", "10"]) == 0
    assert commands == ["GPGGA 0.1"]
    with pytest.raises(SystemExit):
        position_cli.main(["/dev/test", "--rate-hz", "100"])


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
