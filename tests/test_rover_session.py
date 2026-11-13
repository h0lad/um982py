from threading import Event

from conftest import ReplayTransport
from test_bodies import manual_message
from um982py import Receiver, ReconnectPolicy, RoverSession
from um982py.errors import TransportClosed


def test_rover_session_reconnects_receiver_and_reports_connection_health() -> None:
    class Disconnected(ReplayTransport):
        def read(self, size: int, timeout: float) -> bytes:
            raise TransportClosed("receiver disconnected")

    first = Disconnected()
    second = ReplayTransport(
        {b"BESTNAVA\r\n": manual_message("BESTNAVA").raw + b"\r\n"}
    )
    connections = iter((first, second))
    configured: list[Receiver] = []
    errors: list[Exception] = []
    session = RoverSession(
        lambda: Receiver(next(connections), timeout=0.1),
        configure=configured.append,
        on_disconnect=errors.append,
        reconnect=ReconnectPolicy(0.001, 0.01),
    )
    stop = Event()
    updates = session.positions(stop, interval=0.001)
    update = next(updates)
    health = session.health()
    assert update.connection == 2 and update.session_id
    assert health.state == "connected" and health.attempts == 2
    assert health.connections == 2 and health.positions == 1
    assert health.stream is not None and health.corrections is None
    assert len(configured) == 2 and len(errors) == 1
    stop.set()
    assert list(updates) == []
    assert session.health().state == "stopped"
    assert first.closed and second.closed
