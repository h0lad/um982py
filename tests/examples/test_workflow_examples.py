import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import pytest
from examples.crs_transform import __main__ as crs_cli
from examples.field_recording import __main__ as recording_cli
from examples.live_position import __main__ as position_cli
from examples.ntrip_sources import __main__ as sources_cli
from examples.postprocessed_rtk import __main__ as ppk_cli

from conftest import ReplayTransport, ascii_message, sentence
from test_bodies import EXAMPLES
from um982py.errors import TransportClosed
from um982py.live import PositionSession, PositionUpdate
from um982py.live_quality import LiveAssessment
from um982py.messages import DopplerVelocity, Fix, Gsa
from um982py.messages.navigation import BestNavigation
from um982py.ntrip import ReconnectPolicy, parse_sourcetable
from um982py.ppk import PpkResult
from um982py.protocol.ascii import parse_ascii
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
        def correction_health(self) -> None:
            return None

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


def test_live_example_deduplicates_and_reports_doppler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = ascii_message(
        "DOPPVELA",
        "SOL_COMPUTED,DOPPLER_VELOCITY,0.0,0.0,10.0,90.0,2.0,0.3,0.4",
    )
    gsa_raw = sentence(b"GPGSA,A,3,1,2,3,4,5,6,,,,,,,1.2,0.9,0.8,1")

    class Session:
        def __init__(
            self,
            factory: object,
            *,
            configure: object,
            on_message: object,
            subscribe: bool,
        ) -> None:
            del subscribe
            on_message(parse_ascii(raw))  # type: ignore[operator]
            on_message(parse_ascii(gsa_raw))  # type: ignore[operator]

        def correction_health(self) -> None:
            return None

        def positions(self, stop: object) -> object:
            del stop
            fix = Fix("120000", 50, 8, 4, 10, 1, 100, 45, 1, "base")
            for _ in range(2):
                yield PositionUpdate(fix, datetime(2020, 1, 1, tzinfo=UTC), 1, None, 1)

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    assert position_cli.main(["/dev/test", "--plain"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "fix_type=RTK fixed (4)" in lines[0]
    assert "speed_mps=10.0" in lines[0]
    assert "speed_kmh=36.0" in lines[0]
    assert "speed_std_mps=0.4" in lines[0]
    assert "pdop=1.2" in lines[0]


def test_library_labels_doppler_predicted_gga() -> None:
    predicted = Fix("120000", 50, 8, 1, 0, 1, 100, 45, 1, "")
    standalone = Fix("120000", 50, 8, 1, 12, 1, 100, 45, 1, "")
    assert predicted.quality_label == "Doppler predicted"
    assert standalone.quality_label == "standalone"


def test_live_declared_correction_is_marked_unused_for_standalone() -> None:
    navigation = BestNavigation.from_message(parse_ascii(EXAMPLES["BESTNAVA"].encode()))
    fix = Fix("120000", 50, 8, 1, 12, 1, 100, 45, 1, "")
    assert (
        position_cli._correction_label("e6-has", navigation, fix)
        == "E6-HAS declared, unused"
    )


def test_live_formats_adaptive_precision_and_speed() -> None:
    assert position_cli._precision(0.004) == "4.0 mm"
    assert position_cli._precision(0.069) == "6.9 cm"
    assert position_cli._precision(1.18) == "1.18 m"
    assert position_cli._precision(12.3) == "12.3 m"
    assert position_cli._speed(10.0) == "10.000 m/s (36.000 km/h)"
    assert position_cli._speed(10.0, compact=True) == "36.000 km/h"


def test_live_dashboard_render_contains_motion_and_stats() -> None:
    fix = Fix("120000", 50, 8, 5, 10, 1, 100, 45, 1, "base")
    now = monotonic()
    update = PositionUpdate(fix, datetime(2020, 1, 1, tzinfo=UTC), now, None, 2)
    sample = DopplerVelocity(
        status="SOL_COMPUTED",
        velocity_type="DOPPLER_VELOCITY",
        ground_speed_mps=10.0,
        course_true_deg=90.0,
        vertical_speed_mps=2.0,
        ground_speed_std_mps=0.4,
        vertical_speed_std_mps=0.3,
        latency_s=0.0,
        age_s=0.0,
        epoch_gps_seconds=1.0,
    )
    reading = position_cli.TimedDoppler(sample, now)
    navigation = BestNavigation.from_message(parse_ascii(EXAMPLES["BESTNAVA"].encode()))
    gsa = Gsa(mode="A", fix_mode=3, pdop=1.2, hdop=0.9, vdop=0.8, system_id=1)
    state = position_cli.ScreenState(
        update=update,
        assessment=LiveAssessment(update, 1.0, None, ()),
        doppler=reading,
        navigation=navigation,
        gsa=gsa,
        correction_service="e6-has",
        fixes=3,
        duplicates=1,
        speed_history=[0.1, 0.4, 0.9, 0.5, sample.ground_speed_mps],
    )
    text = position_cli._render(state)
    plain = text
    for code in (
        position_cli.BOLD,
        position_cli.DIM,
        position_cli.RESET,
        position_cli.CYAN,
        position_cli.GREEN,
        position_cli.YELLOW,
        position_cli.RED,
    ):
        plain = plain.replace(code, "")
    assert "RTK float" in plain
    assert "E6-HAS declared" in plain
    assert "SINGLE" in plain
    assert "36.000 km/h" in plain
    assert "std 40.0 cm/s 30.0 cm/s" in plain or "std speed 0.400 m/s" in plain
    assert "std E/N/U" in plain
    assert "PDOP 1.20" in plain
    assert "sats" in plain or "used/tracked" in plain
    assert "duplicates 1" in plain
    assert all(len(line) <= 96 for line in plain.splitlines())


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
        def __init__(
            self,
            factory: object,
            *,
            configure: object,
            on_message: object,
            subscribe: bool,
        ) -> None:
            from unittest.mock import Mock

            del subscribe
            receiver = Mock()
            configure(receiver)  # type: ignore[operator]
            commands.extend(
                call.args[0].text for call in receiver.execute.call_args_list
            )

        def positions(self, stop: object) -> object:
            yield from ()

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    assert position_cli.main(["/dev/test", "--rate-hz", "10"]) == 0
    assert commands == [
        "GPGGA 0.1",
        "BESTNAVB 0.1",
        "DOPPVELB 0.1",
    ]
    commands.clear()
    assert (
        position_cli.main(
            ["/dev/test", "--rate-hz", "10", "--request-gsa", "--rtk-reliability", "2"]
        )
        == 0
    )
    assert commands[0] == "CONFIG RTK RELIABILITY 2"
    assert commands[-1] == "GPGSA 0.1"
    with pytest.raises(SystemExit):
        position_cli.main(["/dev/test", "--rate-hz", "100"])


def test_live_example_enables_weinstadt_ntrip_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Session:
        def __init__(self, factory: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def correction_health(self) -> None:
            return None

        def positions(self, stop: object) -> object:
            yield from ()

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    monkeypatch.delenv("NTRIP_USERNAME", raising=False)
    with pytest.raises(SystemExit):
        position_cli.main(["/dev/test", "--plain", "--ntrip"])
    assert (
        position_cli.main(
            [
                "/dev/test",
                "--plain",
                "--ntrip",
                "--ntrip-username",
                "rover@example.com",
            ]
        )
        == 0
    )
    assert captured["ntrip_url"] == position_cli.DEFAULT_NTRIP_URL
    assert captured["ntrip_username"] == "rover@example.com"
    assert captured["ntrip_password"] == position_cli.RTK2GO_PASSWORD
    assert captured["subscribe"] is True


def test_live_example_accepts_scheme_less_rtk2go_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Session:
        def __init__(self, factory: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def correction_health(self) -> None:
            return None

        def positions(self, stop: object) -> object:
            yield from ()

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    monkeypatch.delenv("NTRIP_PASSWORD", raising=False)
    assert (
        position_cli.main(
            [
                "/dev/test",
                "--plain",
                "--ntrip-url",
                "rtk2go.com:2101/BAUER_HAUS",
                "--ntrip-username",
                "rover@example.com",
            ]
        )
        == 0
    )
    assert captured["ntrip_url"] == "http://rtk2go.com:2101/BAUER_HAUS"
    assert captured["ntrip_password"] == position_cli.RTK2GO_PASSWORD


def test_live_example_tolerates_rejected_optional_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from unittest.mock import Mock

    from um982py.errors import CommandRejected

    class Session:
        def __init__(
            self,
            factory: object,
            *,
            configure: object,
            on_message: object,
            subscribe: bool,
        ) -> None:
            del subscribe
            receiver = Mock()
            receiver.execute.side_effect = [
                None,
                None,
                CommandRejected("DOPPVELB 1", "NOT SUPPORTED"),
            ]
            configure(receiver)  # type: ignore[operator]

        def positions(self, stop: object) -> object:
            yield from ()

    monkeypatch.setattr(position_cli, "PositionSession", Session)
    assert position_cli.main(["/dev/test", "--plain"]) == 0
    assert "optional log unavailable: DOPPVEL (NOT SUPPORTED)" in (
        capsys.readouterr().err
    )


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
