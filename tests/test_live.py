from datetime import UTC, datetime
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from conftest import ReplayTransport, ascii_message, sentence
from um982py.errors import TransportClosed
from um982py.live import PositionSession
from um982py.ntrip import ReconnectPolicy
from um982py.protocol.ascii import parse_ascii
from um982py.receiver import Receiver
from um982py.rover_session import RoverSession


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

    def _receive_timed(self, *, timeout: float) -> object:
        del timeout
        try:
            return SimpleNamespace(
                message=parse_ascii(next(self.frames)),
                received_at=datetime.now(UTC),
                received_monotonic=monotonic(),
            )
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


def test_position_session_passes_non_gga_frames_to_callback() -> None:
    raw = ascii_message(
        "DOPPVELA",
        "SOL_COMPUTED,DOPPLER_VELOCITY,0.0,0.0,10.0,90.0,2.0,0.3,0.4",
    )
    doppler = parse_ascii(raw)
    receiver = FakeReceiver([raw])
    seen: list[object] = []
    session = PositionSession(
        lambda: receiver,  # type: ignore[arg-type]
        on_message=lambda message: seen.append(message),
    )
    frame = receiver._receive_timed(timeout=1.0)
    assert (
        session._position_update(
            frame.message, frame.received_at, frame.received_monotonic, 1
        )
        is None
    )
    assert seen == [doppler]


def test_position_session_subscription_delivers_gga_frames() -> None:
    transport = ReplayTransport(chunk=65536)
    transport.pending.extend(gga(4) + gga(4))
    seen: list[object] = []
    session = PositionSession(
        lambda: Receiver(transport),  # type: ignore[arg-type]
        on_message=seen.append,
        subscribe=True,
        poll_seconds=0.01,
    )
    updates = session.positions(Event())
    first = next(updates)
    second = next(updates)
    assert first.fix.quality == second.fix.quality == 4
    assert first.connection == second.connection == 1
    assert session.health().fixes == 2
    assert len(seen) == 2
    updates.close()
    assert session.health().state == "stopped"


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


@pytest.mark.parametrize("session_type", [PositionSession, RoverSession])
@pytest.mark.parametrize("option", ["receiver_factory", "configure", "on_disconnect"])
def test_sessions_reject_non_callable_inputs_before_connecting(
    session_type: type[PositionSession] | type[RoverSession], option: str
) -> None:
    options = {"receiver_factory": lambda: pytest.fail("unexpected connection")}
    options[option] = 42  # type: ignore[assignment]
    with pytest.raises(TypeError, match=f"{option} must be callable"):
        session_type(**options)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "seconds", [True, False, 0, -1, 61, float("nan"), float("inf")]
)
def test_position_session_rejects_invalid_poll_seconds(seconds: float) -> None:
    with pytest.raises(ValueError, match="poll_seconds"):
        PositionSession(
            lambda: pytest.fail("unexpected connection"), poll_seconds=seconds
        )
