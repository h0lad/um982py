from concurrent.futures import Future
from threading import Event
from time import sleep

import pytest

from conftest import rtcm
from um982py.messages import RtcmMessage
from um982py.ntrip import NtripError, ReconnectPolicy
from um982py.rtk_session import CorrectionWriteError, RtkSession


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
