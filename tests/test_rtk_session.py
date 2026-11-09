from concurrent.futures import Future
from threading import Event
from time import sleep

import pytest

from conftest import FIXTURES, ReplayTransport, acknowledgement, rtcm, sentence
from um982py import Receiver, relay_ntrip
from um982py.commands.core import action
from um982py.errors import ResponseTimeout
from um982py.messages import RtcmMessage
from um982py.ntrip import NtripError, ReconnectPolicy
from um982py.protocol.ascii import parse_ascii
from um982py.rtk_session import CorrectionWriteError, GgaProviderError, RtkSession


class Caster:
    def __init__(self, data: list[bytes], failure: Exception | None = None) -> None:
        self.data = data
        self.failure = failure
        self.closed = False

    def connect(self) -> None:
        if self.failure:
            raise self.failure

    def set_read_timeout(self, seconds: float) -> None:
        assert seconds > 0

    def read(self) -> bytes:
        return self.data.pop(0)

    def close(self) -> None:
        self.closed = True


class Stream:
    def __init__(self, stop: Event, *, fail: bool = False) -> None:
        self.stop = stop
        self.fail = fail
        self.forwarded: list[bytes] = []

    def send_correction(self, message: RtcmMessage) -> Future[None]:
        future: Future[None] = Future()
        if self.fail:
            future.set_exception(OSError("serial disconnected"))
        else:
            self.forwarded.append(message.raw)
            self.stop.set()
            future.set_result(None)
        return future


def test_simple_relay_cleans_up_worker_if_configuration_is_invalid() -> None:
    transport = ReplayTransport({b"RESET\r\n": acknowledgement("RESET")})
    with Receiver(transport) as receiver:
        with pytest.raises(ValueError, match="URL"):
            relay_ntrip(receiver, "invalid")
        assert not transport.closed
        assert receiver.execute(action("RESET")).accepted


def test_from_url_queries_current_fix_for_each_connection_and_update() -> None:
    class GgaStream:
        def __init__(self) -> None:
            self.responses = [
                parse_ascii(sentence(b"GNGGA,120000,5200,N,01300,E,1,10,1,2,M,3,M,,")),
                parse_ascii(sentence(b"GNGGA,120001,,,,,0,00,,,,,,,")),
                ResponseTimeout("no fix"),
            ]

        def execute(self, command: object, *, timeout: float) -> Future[object]:
            assert timeout == 2
            future: Future[object] = Future()
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                future.set_exception(response)
            else:
                future.set_result(response)
            return future

    session = RtkSession.from_url(
        GgaStream(),
        "http://caster.example/MOUNT",  # type: ignore[arg-type]
    )
    client = session.client_factory()
    assert client.initial_gga == sentence(
        b"GPGGA,120000,5200,N,01300,E,1,10,1,2,M,3,M,,"
    )
    assert session.gga_provider is not None
    assert session.gga_provider() is None
    assert session.client_factory().initial_gga is None


def test_from_url_validates_options_and_reports_gga_failures() -> None:
    stream = Stream(Event())
    with pytest.raises(ValueError, match="username and password"):
        RtkSession.from_url(stream, "http://caster.example/MOUNT", username="user")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="GGA timeout"):
        RtkSession.from_url(stream, "http://caster.example/MOUNT", gga_timeout=0)  # type: ignore[arg-type]
    session = RtkSession.from_url(stream, "http://caster.example/MOUNT")  # type: ignore[arg-type]
    with pytest.raises(GgaProviderError, match="GGA provider failed"):
        session.run(Event())
    assert session.health().state == "failed"


def test_reconnect_after_eof_and_forward_complete_rtcm() -> None:
    stop = Event()
    frame = rtcm(b"\x3e\xd0")
    clients = [Caster([b""]), Caster([frame[:3], frame[3:]])]
    stream = Stream(stop)
    session = RtkSession(
        stream,  # type: ignore[arg-type]
        lambda: clients.pop(0),  # type: ignore[arg-type]
        reconnect=ReconnectPolicy(0.001, 0.002),
    )
    session.run(stop)
    health = session.health()
    assert health.state == "stopped"
    assert (health.connection_attempts, health.reconnects, health.frames_forwarded) == (
        2,
        1,
        1,
    )
    assert health.last_byte_monotonic is not None
    assert health.last_correction_monotonic is not None
    assert health.message_counts == ((1005, 1),)
    assert health.correction_age is not None and health.correction_age >= 0
    assert stream.forwarded == [frame]


def test_authentication_and_receiver_write_failures_do_not_retry() -> None:
    stop = Event()
    auth = Caster([], NtripError("unauthorized", status_code=401))
    session = RtkSession(Stream(stop), lambda: auth)  # type: ignore[arg-type]
    with pytest.raises(NtripError):
        session.run(stop)
    assert session.health().state == "failed"
    assert session.health().connection_attempts == 1
    assert auth.closed

    caster = Caster([rtcm(b"\x3e\xd0")])
    session = RtkSession(Stream(stop, fail=True), lambda: caster)  # type: ignore[arg-type]
    with pytest.raises(CorrectionWriteError):
        session.run(stop)
    assert session.health().connection_attempts == 1


def test_gga_is_sent_when_caster_times_out() -> None:
    stop = Event()

    class IdleCaster(Caster):
        def read(self) -> bytes:
            sleep(0.015)
            raise TimeoutError

        def send_gga(self, data: bytes) -> None:
            assert data == b"gga"
            stop.set()

    caster = IdleCaster([])
    session = RtkSession(
        Stream(stop),  # type: ignore[arg-type]
        lambda: caster,  # type: ignore[arg-type]
        gga_provider=lambda: b"gga",
        gga_interval=0.01,
    )
    session.run(stop)
    assert caster.closed


def test_gga_provider_failure_is_not_retried_as_a_caster_error() -> None:
    stop = Event()

    class IdleCaster(Caster):
        def read(self) -> bytes:
            sleep(0.015)
            raise TimeoutError

    def failed_gga() -> bytes | None:
        raise OSError("receiver disconnected")

    caster = IdleCaster([])
    session = RtkSession(
        Stream(stop),  # type: ignore[arg-type]
        lambda: caster,  # type: ignore[arg-type]
        gga_provider=failed_gga,
        gga_interval=0.01,
    )
    with pytest.raises(GgaProviderError):
        session.run(stop)
    assert session.health().state == "failed"
    assert session.health().connection_attempts == 1


def test_relay_ntrip_forwards_corrections_and_sends_initial_gga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.examples.test_ntrip_client import FakeSocket
    from um982py import ReceiverStream
    from um982py.protocol import StreamDecoder

    frames = [rtcm((kind << 4).to_bytes(2, "big")) for kind in (1005, 1077, 1087)]
    connection = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n" + b"".join(frames))

    def fragmented_recv(size: int) -> bytes:
        return connection.reply.read(min(size, 7))

    monkeypatch.setattr(connection, "recv", fragmented_recv)
    monkeypatch.setattr("socket.create_connection", lambda *args: connection)
    transport = ReplayTransport(
        {
            b"GPGGA\r\n": (FIXTURES / "captures-live/GNGGA.bin").read_bytes(),
        }
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
    with Receiver(transport) as receiver:
        relay_ntrip(
            receiver,
            "http://caster.example:2101/STATION",
            username="researcher",
            password="test-credential",  # noqa: S106
        )
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
