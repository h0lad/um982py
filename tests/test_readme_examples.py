"""Run the README snippets unchanged against recorded receiver responses."""

import json
import re
from pathlib import Path

import pytest

from conftest import ReplayTransport, SubscriptionTransport, rtcm, sentence
from um982py import Receiver, ReceiverStream, RtkSession
from um982py.commands.types import Port
from um982py.messages import RtcmMessage
from um982py.protocol import StreamDecoder
from um982py.rinex import RinexExport

ROOT = Path(__file__).resolve().parents[1]
SNIPPETS = re.findall(
    r"```python\n(.*?)```", (ROOT / "README.md").read_text(encoding="utf-8"), re.S
)


def _run_snippet(
    index: int,
    capture: str | bytes,
    command: bytes,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    queries: int = 1,
) -> dict[str, object]:
    raw = (
        capture
        if isinstance(capture, bytes)
        else (ROOT / "tests" / "fixtures" / capture).read_bytes()
    )
    transport = ReplayTransport({command: raw}, chunk=7)

    def serial(port: str, baudrate: int, *, timeout: float = 3) -> Receiver:
        assert (port, baudrate) == ("/dev/ttyUSB0", 921600)
        assert timeout > 0
        return Receiver(transport, timeout=0.1)

    monkeypatch.setattr(Receiver, "serial", staticmethod(serial))
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(compile(SNIPPETS[index], "README.md", "exec"), namespace)  # noqa: S102
    assert transport.writes == [command] * queries
    assert transport.closed
    return namespace


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        (
            sentence(
                b"GNGGA,145842.00,5232.0000,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,"
            ),
            "52.53333333333333, 13.366666666666667 | quality: 1 | 17 satellites | "
            "RTK fixed: False\n",
        ),
        (sentence(b"GNGGA,145842.00,,,,,0,00,,,,,,,"), "Waiting for a position\n"),
    ],
)
def test_readme_position(
    capture: bytes,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    _run_snippet(0, capture, b"GPGGA\r\n", monkeypatch, tmp_path, queries=60)
    assert capsys.readouterr().out == expected * 60


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        ("captures-live/GNTHS.bin", "Heading: 275.1° clockwise from true north\n"),
        ("gpths.bin", "Dual-antenna heading is not available yet\n"),
    ],
)
def test_readme_heading(
    capture: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(1, capture, b"GPTHS\r\n", monkeypatch, tmp_path)
    assert capsys.readouterr().out == expected


def test_readme_ntrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.examples.test_ntrip_client import FakeSocket

    frames = [rtcm((kind << 4).to_bytes(2, "big")) for kind in (1005, 1077, 1087)]
    connection = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n" + b"".join(frames))

    def fragmented_recv(size: int) -> bytes:
        return connection.reply.read(min(size, 7))

    monkeypatch.setattr(connection, "recv", fragmented_recv)
    monkeypatch.setattr("socket.create_connection", lambda *args: connection)
    monkeypatch.setenv("NTRIP_URL", "http://caster.example:2101/STATION")
    monkeypatch.setenv("NTRIP_USERNAME", "researcher")
    monkeypatch.setenv("NTRIP_PASSWORD", "test-credential")
    transport = ReplayTransport(
        {
            b"GPGGA\r\n": (
                ROOT / "tests/fixtures/captures-live/GNGGA.bin"
            ).read_bytes(),
        }
    )
    monkeypatch.setattr(
        Receiver, "serial", staticmethod(lambda *args: Receiver(transport))
    )
    active_stop = []
    send = ReceiverStream.send_correction
    run = RtkSession.run

    def stop_after_last(stream: ReceiverStream, message: RtcmMessage) -> object:
        future = send(stream, message)
        if message.message_type == 1087:
            future.add_done_callback(lambda _: active_stop[0].set())
        return future

    def run_until_complete(session: RtkSession, stop: object) -> None:
        active_stop.append(stop)
        run(session, stop)  # type: ignore[arg-type]

    monkeypatch.setattr(ReceiverStream, "send_correction", stop_after_last)
    monkeypatch.setattr(RtkSession, "run", run_until_complete)
    exec(compile(SNIPPETS[2], "README.md", "exec"), {})  # noqa: S102
    forwarded = [data for data in transport.writes if data.startswith(b"\xd3")]
    assert forwarded == frames
    assert transport.closed
    assert transport.writes.count(b"GPGGA\r\n") >= 1
    assert b"Ntrip-GGA: $GPGGA," in connection.sent[0]
    assert b"Authorization: Basic " in connection.sent[0]
    decoder = StreamDecoder(strict=True)
    assert all(
        isinstance(frame, RtcmMessage) for frame in decoder.feed(b"".join(forwarded))
    )
    decoder.finish()


def test_readme_rinex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = [0.0]

    class SessionTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += timeout
            return super().read(size, timeout)

    transport = SessionTransport()
    transport.after_write["RANGEB 1"] = (
        ROOT / "tests/fixtures/captures-live/RANGEA.bin"
    ).read_bytes()
    monkeypatch.setattr("um982py.capture.monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        Receiver, "serial", staticmethod(lambda *args: Receiver(transport, timeout=1))
    )
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(compile(SNIPPETS[3], "README.md", "exec"), namespace)  # noqa: S102
    result = namespace["result"]
    assert isinstance(result, RinexExport)
    assert result.epochs == 26
    assert result.satellite_records == 898
    assert result.signal_observations == 1524
    assert result.omitted == {
        "invalid_code_or_phase": 719,
        "unverified_l2c_component": 104,
    }
    assert transport.closed
    assert ("RANGEB", Port.COM1) not in transport.subscriptions
    text = (tmp_path / "field.obs").read_text(encoding="ascii")
    assert text == result.text
    assert text.startswith("     3.05")
    assert "FIELD01" in text
    assert text.count("\n> ") == 26


def test_readme_speed_and_coordinate_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = json.loads(
        (ROOT / "tests/fixtures/manual-examples-r1.4.json").read_text(encoding="utf-8")
    )
    namespace = _run_snippet(
        4,
        (samples["BESTNAVA"] + "\r\n").encode("ascii"),
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    from um982py import BestNavigation, geodetic_from_ecef

    navigation = namespace["navigation"]
    assert isinstance(navigation, BestNavigation)
    assert navigation.valid and navigation.velocity_valid
    assert "Horizontal speed in m/s: 0.0046" in capsys.readouterr().out
    xyz = namespace["xyz"]
    assert isinstance(xyz, tuple)
    assert geodetic_from_ecef(*xyz) == pytest.approx(
        (navigation.latitude, navigation.longitude, navigation.ellipsoidal_height),
        abs=1e-5,
    )


def test_readme_pps_edge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import um982py
    from um982py import PpsEdge, PpsSnapshot

    class Device:
        def __init__(self, path: str) -> None:
            assert path == "/dev/pps0"

        def __enter__(self) -> "Device":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch(self) -> PpsSnapshot:
            return PpsSnapshot(PpsEdge("assert", 1, 1, 123), None, 0)

    monkeypatch.setattr(um982py, "PpsDevice", Device)
    exec(compile(SNIPPETS[5], "README.md", "exec"), {})  # noqa: S102
    assert capsys.readouterr().out == "Host CLOCK_REALTIME in nanoseconds: 1000000123\n"
