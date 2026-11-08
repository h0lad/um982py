from threading import Event

import pytest

from conftest import sentence
from um982py.errors import TransportClosed
from um982py.live import PositionSession
from um982py.ntrip import ReconnectPolicy
from um982py.protocol.ascii import parse_ascii


def gga(quality: int) -> bytes:
    return sentence(
        f"GPGGA,123519,4807.038,N,01131.000,E,{quality},08,0.9,545.4,M,46.9,M,1.2,0001".encode()
    )


class FakeReceiver:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = iter(frames)
        self.closed = False

    def __enter__(self) -> "FakeReceiver":
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def receive(self, *, timeout: float) -> object:
        del timeout
        try:
            return parse_ascii(next(self.frames))
        except StopIteration:
            raise TransportClosed("disconnected") from None


def test_position_session_reconnects_and_reports_quality_changes() -> None:
    first = FakeReceiver([sentence(b"GPGGA,1"), gga(4)])
    second = FakeReceiver([gga(5)])
    receivers = iter((first, second))
    configured = []
    session = PositionSession(
        lambda: next(receivers),  # type: ignore[arg-type]
        configure=configured.append,
        reconnect=ReconnectPolicy(0.001, 0.001),
    )
    updates = session.positions(Event())
    a = next(updates)
    b = next(updates)
    assert a.fix.valid and a.fix.ellipsoidal_height == pytest.approx(592.3)
    assert a.previous_quality is None and not a.quality_changed
    assert b.previous_quality == 4 and b.quality_changed and b.connection == 2
    assert configured == [first, second]
    assert session.health().malformed_fixes == 1
    assert session.health().attempts == 2
    updates.close()
    assert first.closed and second.closed and session.health().state == "stopped"


def test_position_session_propagates_configuration_error() -> None:
    receiver = FakeReceiver([])

    def reject(_: object) -> None:
        raise ValueError("bad configuration")

    session = PositionSession(lambda: receiver, configure=reject)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bad configuration"):
        next(session.positions(Event()))
    assert receiver.closed
    assert session.health().state == "failed"


def test_position_session_stops_before_connecting() -> None:
    stop = Event()
    stop.set()
    session = PositionSession(lambda: pytest.fail("unexpected connection"))
    assert list(session.positions(stop)) == []
    assert session.health().attempts == 0
