"""Exercise the NTRIP example with a simulated receiver and caster."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from examples.ntrip_client import (
    CorrectionStats,
    ReferenceStation,
    forward_corrections,
    gga_from_fix,
)
from examples.ntrip_client import __main__ as ntrip_main
from examples.ntrip_client.__main__ import _reference_check, _report, _sample, main
from examples.ntrip_client.precision import PrecisionMonitor, precision_line
from examples.position_tracking import TrackPoint

from um982py import NtripClient
from um982py.commands import Log
from um982py.errors import ResponseTimeout
from um982py.geodesy import ecef_from_geodetic
from um982py.messages import Record
from um982py.messages.navigation import Fix
from um982py.ntrip import NtripError, ReconnectPolicy, retryable_ntrip_error
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import parse_rtcm
from um982py.protocol.checksums import rtcm_crc24q


class FakeSocket:
    def __init__(self, reply: bytes) -> None:
        self.reply = BytesIO(reply)
        self.sent: list[bytes] = []

    def settimeout(self, timeout: float) -> None:
        pass

    def recv(self, size: int) -> bytes:
        return self.reply.read(size)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        pass


def test_reconnection_retries_caster_and_preserves_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    attempts: list[float] = []

    def once(*args: object) -> None:
        attempts.append(clock[0])
        if len(attempts) < 3:
            raise ntrip_main.CasterDisconnected("test disconnect")

    monkeypatch.setattr(ntrip_main, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        ntrip_main, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(ntrip_main, "_stream_once", once)
    args = ntrip_main._parser().parse_args(["--duration", "10"])
    ntrip_main._stream(None, args, CorrectionStats(), PrecisionMonitor(), None)  # type: ignore[arg-type]
    assert attempts == [0.0, 1.0, 3.0]


def test_reconnection_rejects_auth_and_receiver_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ReconnectPolicy(1, 4)
    assert [policy.next_delay(n) for n in (1, 2, 4)] == [2, 4, 4]
    assert retryable_ntrip_error(NtripError("busy", status_code=503))
    assert not retryable_ntrip_error(NtripError("unauthorized", status_code=401))
    args = ntrip_main._parser().parse_args(["--duration", "10"])

    def receiver_failure(*args: object) -> None:
        raise OSError("receiver disconnected")

    monkeypatch.setattr(ntrip_main, "_stream_once", receiver_failure)
    with pytest.raises(OSError, match="receiver disconnected"):
        ntrip_main._stream(None, args, CorrectionStats(), PrecisionMonitor(), None)  # type: ignore[arg-type]


def frame(message_type: int) -> bytes:
    payload = (message_type << 4).to_bytes(2, "big") + b"\x01\x02"
    body = b"\xd3\x00" + bytes((len(payload),)) + payload
    return body + rtcm_crc24q(body).to_bytes(3, "big")


def station_frame() -> bytes:
    size = 19
    bits = size * 8
    packed = (1005 << (bits - 12)) | (42 << (bits - 24))
    for start, coordinate in zip(
        (34, 74, 114), ecef_from_geodetic(52.5200, 13.4050, 100.0), strict=True
    ):
        packed |= (round(coordinate * 10000) & ((1 << 38) - 1)) << (bits - start - 38)
    body = b"\xd3\x00" + bytes((size,)) + packed.to_bytes(size, "big")
    return body + rtcm_crc24q(body).to_bytes(3, "big")


def test_reconnect_discards_partial_frame_from_previous_connection() -> None:
    class ReceiverStub:
        def __init__(self) -> None:
            self.frames: list[bytes] = []

        def send_correction(self, message: object) -> None:
            self.frames.append(message.raw)  # type: ignore[attr-defined]

        def execute(self, command: object, *, timeout: float | None = None) -> None:
            raise ResponseTimeout("test")

        def drain_pending(self) -> tuple[()]:
            return ()

    class WaitingSocket(FakeSocket):
        def recv(self, size: int) -> bytes:
            data = super().recv(size)
            if not data:
                raise TimeoutError
            return data

    complete = frame(1077)
    first = FakeSocket(b"ICY 200 OK\r\n" + complete[:3])
    second = WaitingSocket(b"ICY 200 OK\r\n" + complete[3:] + complete)
    receiver = ReceiverStub()
    stats = CorrectionStats()
    args = ntrip_main._parser().parse_args(
        [
            "--no-gga",
            "--duration",
            "0.05",
            "--ntrip-version",
            "1",
            "--caster",
            "http://caster.test:2101/BASE",
            "--reconnect-delay",
            "0.001",
            "--reconnect-max-delay",
            "0.001",
        ]
    )
    with patch("socket.create_connection", side_effect=[first, second]):
        ntrip_main._stream(receiver, args, stats, PrecisionMonitor(), None)  # type: ignore[arg-type]
    assert receiver.frames == [complete]
    assert stats.frames_forwarded == 1 and stats.connection_failures == 1


def test_ntrip_v1_sends_gga_after_connecting() -> None:
    connection = FakeSocket(b"ICY 200 OK\r\n" + frame(1077))
    fix = Fix("", 50.5, 8.25, 1, 12, 0.8, 100.0, 45.0, None, "")
    gga = gga_from_fix(fix, now=datetime(2026, 1, 1, 12, 30, tzinfo=UTC))
    credential = "none"
    with (
        patch("socket.create_connection", return_value=connection),
        NtripClient(
            "http://caster.test:2101/BASE",
            username="user",
            password=credential,
            initial_gga=gga,
            version=1,
        ) as caster,
    ):
        assert caster.read() == frame(1077)
    assert connection.sent[0].startswith(b"GET /BASE HTTP/1.0\r\n")
    assert connection.sent[1] == gga
    assert parse_ascii(gga).fields[1:5] == (
        "5030.000000",
        "N",
        "00815.000000",
        "E",
    )


@pytest.mark.parametrize("value", [None, 0.0])
def test_gga_preserves_missing_and_zero_receiver_values(value: float | None) -> None:
    fix = Fix("", 50.5, 8.25, 1, 12, value, value, value, None, "")
    gga = gga_from_fix(fix, now=datetime(2026, 1, 1, 12, 30, tzinfo=UTC))
    parsed = Fix.from_message(parse_ascii(gga))
    assert (parsed.hdop, parsed.altitude_msl, parsed.geoid_separation) == (
        value,
        value,
        value,
    )


def test_reference_comparison_requires_fresh_station_and_receiver_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ntrip_main, "monotonic", lambda: 100.0)
    xyz = ecef_from_geodetic(50.0, 8.0, 100.0)

    class ReceiverStub:
        status = 0

        def execute(self, command: object, *, timeout: float) -> Record:
            return Record(
                "BASEINFO",
                (("status", self.status), *zip(("x", "y", "z"), xyz, strict=True)),
            )

        def drain_pending(self) -> tuple[()]:
            return ()

    stats = CorrectionStats(
        station=ReferenceStation(42, 50.0, 8.0, 100.0), station_received_at=95.0
    )
    receiver = ReceiverStub()
    assert _reference_check(receiver, stats, 1.0)  # type: ignore[arg-type]
    assert stats.reference_difference_m == pytest.approx(0, abs=1e-6)
    assert stats.reference_queried_at == 100
    receiver.status = 1
    assert _reference_check(receiver, stats, 1.0)  # type: ignore[arg-type]
    assert stats.reference_difference_m is None
    receiver.status = 0
    stats.station_received_at = 79
    assert _reference_check(receiver, stats, 1.0)  # type: ignore[arg-type]
    assert stats.reference_difference_m is None
    assert stats.reference_queried_at is None


def test_reference_comparison_is_invalidated_when_station_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReceiverStub:
        def send_correction(self, message: object) -> None:
            pass

    old = ReferenceStation(42, 50.0, 8.0, 100.0)
    new = ReferenceStation(43, 50.0, 8.0, 100.0)
    stats = CorrectionStats(
        station=old, reference_difference_m=0.0, reference_queried_at=1.0
    )
    monkeypatch.setattr(ReferenceStation, "from_rtcm", lambda message: new)
    forward_corrections(
        ReceiverStub(),
        station_frame(),
        decoder=StreamDecoder(),
        stats=stats,  # type: ignore[arg-type]
    )
    assert stats.station == new
    assert stats.station_received_at is not None
    assert stats.reference_difference_m is None
    assert stats.reference_queried_at is None


@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        ("http://caster.test:2101/BASE", b"caster.test:2101"),
        ("http://caster.test:80/BASE", b"caster.test"),
        ("http://[2001:db8::1]:2101/BASE", b"[2001:db8::1]:2101"),
    ],
)
def test_ntrip_host_header_matches_the_url(url: str, expected_host: bytes) -> None:
    connection = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n")
    with patch("socket.create_connection", return_value=connection), NtripClient(url):
        pass
    assert b"\r\nHost: " + expected_host + b"\r\n" in connection.sent[0]


def test_ntrip_rejects_port_zero() -> None:
    with pytest.raises(ValueError, match="port"):
        NtripClient("http://caster.test:0/BASE")


def test_ntrip_closes_socket_if_tls_context_creation_fails() -> None:
    connection = FakeSocket(b"")
    with (
        patch("socket.create_connection", return_value=connection),
        patch.object(connection, "close") as close,
        patch("ssl.create_default_context", side_effect=OSError("TLS failed")),
        pytest.raises(OSError, match="TLS failed"),
    ):
        NtripClient("https://caster.test/BASE").connect()
    close.assert_called_once_with()


def test_ntrip_closes_tls_socket_if_setting_timeout_fails() -> None:
    connection = FakeSocket(b"")
    tls_connection = FakeSocket(b"")
    with (
        patch("socket.create_connection", return_value=connection),
        patch("ssl.create_default_context") as context,
        patch.object(tls_connection, "settimeout", side_effect=OSError("timeout")),
        patch.object(tls_connection, "close") as close,
        pytest.raises(OSError, match="timeout"),
    ):
        context.return_value.wrap_socket.return_value = tls_connection
        NtripClient("https://caster.test/BASE").connect()
    close.assert_called_once_with()


def test_forwarding_keeps_only_valid_rtcm_and_reads_base_position() -> None:
    class ReceiverStub:
        def __init__(self) -> None:
            self.frames: list[bytes] = []

        def send_correction(self, message: object) -> None:
            self.frames.append(message.raw)

    valid = frame(1077)
    damaged = valid[:-1] + bytes((valid[-1] ^ 1,))
    receiver = ReceiverStub()
    stats = CorrectionStats()
    forwarded = forward_corrections(
        receiver,
        valid + damaged + station_frame(),
        decoder=StreamDecoder(),
        stats=stats,
    )
    assert forwarded == 2
    assert receiver.frames == [valid, station_frame()]
    assert stats.message_types == {1077: 1, 1005: 1}
    assert stats.station is not None
    assert stats.station.station_id == 42
    assert stats.station.distance_km(52.5200, 13.4050) < 0.001
    assert ReferenceStation.from_rtcm(parse_rtcm(station_frame())) is not None


def test_sample_accepts_new_receiver_epochs() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures/bodies/SPPNAVB.bin"
    command = Log.SPPNAV.read(binary=True)
    record = next(
        command.decode(message)
        for message in StreamDecoder().feed(path.read_bytes())
        if command.matches(message)
    )

    class ReceiverStub:
        def execute(self, command: object, *, timeout: float) -> object:
            assert command.text == "SPPNAVB"
            return record

        def drain_pending(self) -> tuple[()]:
            return ()

    samples: list[TrackPoint] = []
    assert _sample(
        ReceiverStub(), Log.SPPNAV, samples, antenna="primary", timeout=0.5, debug=False
    )
    assert _sample(
        ReceiverStub(), Log.SPPNAV, samples, antenna="primary", timeout=0.5, debug=False
    )
    assert len(samples) == 1
    assert samples[0].position_type == "SINGLE"


def test_position_selection_uses_current_lower_sigma() -> None:
    code = TrackPoint(
        100, 48, 9, 260, None, 20, "PSRDIFF", source="SPPNAV", horizontal_sigma_m=2
    )
    float_fix = TrackPoint(
        100,
        48,
        9,
        260,
        None,
        20,
        "NARROW_FLOAT",
        source="ADRNAV",
        horizontal_sigma_m=12,
    )
    monitor = PrecisionMonitor(corrected=[code], rtk=[float_fix])
    assert monitor.position() is code
    fixed = TrackPoint(
        100,
        48,
        9,
        260,
        None,
        20,
        "NARROW_INT",
        source="ADRNAV",
        horizontal_sigma_m=0.02,
    )
    monitor.rtk[-1] = fixed
    assert monitor.position() is fixed


def test_baseline_summary_reports_receiver_estimate() -> None:
    before = TrackPoint(
        100,
        48,
        9,
        260,
        None,
        20,
        "SINGLE",
        horizontal_sigma_m=2.5,
        height_sigma_m=3.0,
    )
    after = TrackPoint(
        101,
        48,
        9,
        260,
        None,
        20,
        "PSRDIFF",
        horizontal_sigma_m=1.5,
        height_sigma_m=2.0,
        correction_age_s=2.0,
    )
    line = precision_line(PrecisionMonitor(baseline=[before], corrected=[after]))
    assert "2.500 m -> 1.500 m (40.0% lower)" in line
    assert "height sigma 3.000 m -> 2.000 m" in line
    assert "median correction age 2.0 s" in line


def test_report_shows_each_solution_and_the_selected_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = TrackPoint(
        100, 48, 9, 260, None, 20, "PSRDIFF", source="SPPNAV", horizontal_sigma_m=2
    )
    float_fix = TrackPoint(
        100,
        48,
        9,
        260,
        None,
        20,
        "NARROW_FLOAT",
        source="ADRNAV",
        horizontal_sigma_m=12,
    )
    monitor = PrecisionMonitor(corrected=[code], rtk=[float_fix])
    _report(CorrectionStats(), monitor, debug=False)
    output = capsys.readouterr().err
    assert "SPPNAV PSRDIFF 2.000 m" in output
    assert "ADRNAV NARROW_FLOAT 12.000 m" in output
    assert "selected SPPNAV" in output


def test_requested_command_feeds_corrections_to_receiver() -> None:
    class ReceiverStub:
        def __init__(self) -> None:
            self.commands: list[str] = []
            self.log_commands: list[str] = []
            self.frames: list[bytes] = []
            self.drain_count = 0

        def __enter__(self) -> ReceiverStub:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, command: object, *, timeout: float | None = None) -> None:
            if command.text.endswith("B"):
                self.log_commands.append(command.text)
                raise ResponseTimeout(command.text)
            self.commands.append(command.text)

        def fix(self, *, antenna: int) -> Fix:
            return Fix("", 52.5200, 13.4050, 1, 18, 0.8, 100, 45, None, "")

        def send_correction(self, message: object) -> None:
            self.frames.append(message.raw)

        def drain_pending(self) -> tuple[()]:
            self.drain_count += 1
            return ()

    class StreamingSocket(FakeSocket):
        def recv(self, size: int) -> bytes:
            data = super().recv(size)
            if not data:
                raise TimeoutError
            return data

    payload = frame(1077)
    connection = StreamingSocket(b"ICY 200 OK\r\n" + payload)
    receiver = ReceiverStub()
    with (
        patch("socket.create_connection", return_value=connection),
        patch("examples.ntrip_client.__main__.Receiver.connect", return_value=receiver),
    ):
        result = main(
            [
                "--port",
                "test-device",
                "--baud",
                "921600",
                "--caster",
                "http://rtk2go.com:2101/TEST",
                "--ntrip-version",
                "1",
                "--username",
                "rover@test.invalid",
                "--baseline-seconds",
                "0",
                "--duration",
                "0.01",
                "--debug",
            ]
        )
    assert result == 0
    assert receiver.commands == ["MODE ROVER SURVEY"]
    assert "PPPNAVB" not in receiver.log_commands
    assert "BESTNAVB" not in receiver.log_commands
    assert payload in receiver.frames
    assert receiver.drain_count > 0
    assert b"GET /TEST HTTP/1.0\r\n" in connection.sent[0]
    assert b"Authorization: Basic " in connection.sent[0]
    assert connection.sent[1].startswith(b"$GPGGA,")
