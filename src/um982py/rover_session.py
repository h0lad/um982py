"""Reconnect a rover receiver while maintaining correction and stream status."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from threading import Event, Lock
from time import monotonic
from typing import Literal

from um982py.errors import ResponseTimeout, TransportError
from um982py.ntrip import ReconnectPolicy
from um982py.receiver import Receiver
from um982py.rover import Rover, RoverPosition
from um982py.rtk_session import RtkHealth
from um982py.streaming import StreamHealth

__all__ = ["RoverSession", "RoverSessionHealth", "RoverUpdate"]


@dataclass(frozen=True, slots=True)
class RoverUpdate:
    """A rover position and the receiver connection that produced it."""

    position: RoverPosition
    connection: int
    session_id: str
    completed_monotonic: float


@dataclass(frozen=True, slots=True)
class RoverSessionHealth:
    state: str
    attempts: int
    connections: int
    positions: int
    last_position_monotonic: float | None
    last_error: str | None
    stream: StreamHealth | None
    corrections: RtkHealth | None


class RoverSession:
    """Own reconnecting BESTNAV polling, with optional NTRIP and matched heading.

    Use ``Rover`` for one receiver connection. This class owns a fresh receiver
    and rover worker per connection, exposing both connection and correction
    health. It polls positions rather than acting as a passive GGA
    subscription.

    The factory opens a new receiver each time. The optional configuration
    callback runs before the stream and NTRIP relay start on each connection.
    Transport errors retry with backoff, while protocol, configuration and
    fatal correction errors propagate. Caster reconnection is handled by the relay.
    Close the iterator when stopping early. A stop can wait for in-flight I/O.
    """

    def __init__(
        self,
        receiver_factory: Callable[[], Receiver],
        *,
        configure: Callable[[Receiver], None] | None = None,
        on_disconnect: Callable[[Exception], None] | None = None,
        reconnect: ReconnectPolicy | None = None,
        ntrip_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        ntrip_version: Literal[1, 2] = 2,
    ) -> None:
        if not callable(receiver_factory):
            raise TypeError("receiver_factory must be callable")
        if configure is not None and not callable(configure):
            raise TypeError("configure must be callable")
        if on_disconnect is not None and not callable(on_disconnect):
            raise TypeError("on_disconnect must be callable")
        if ntrip_url is None and (username is not None or password is not None):
            raise ValueError("credentials require an NTRIP URL")
        self.receiver_factory = receiver_factory
        self.configure = configure
        self.on_disconnect = on_disconnect
        self.reconnect = reconnect or ReconnectPolicy()
        self.ntrip_url = ntrip_url
        self.username = username
        self.password = password
        self.ntrip_version = ntrip_version
        self._lock = Lock()
        self._state = "idle"
        self._attempts = 0
        self._connections = 0
        self._positions = 0
        self._last_position: float | None = None
        self._error: str | None = None
        self._rover: Rover | None = None
        self._reconnect_delay = self.reconnect.initial_seconds

    def _require_idle(self) -> None:
        with self._lock:
            if self._state != "idle":
                raise RuntimeError("session can only be run once")
            self._state = "connecting"

    def _begin_connection_attempt(self) -> None:
        with self._lock:
            self._state = "connecting"
            self._attempts += 1

    @contextmanager
    def _connect(self) -> Iterator[tuple[Rover, int]]:
        with self.receiver_factory() as receiver:
            if self.configure is not None:
                self.configure(receiver)
            with Rover(
                receiver,
                ntrip_url=self.ntrip_url,
                username=self.username,
                password=self.password,
                ntrip_version=self.ntrip_version,
            ) as rover:
                with self._lock:
                    self._connections += 1
                    connection = self._connections
                    self._state = "connected"
                    self._rover = rover
                try:
                    yield rover, connection
                finally:
                    with self._lock:
                        self._rover = None

    def _wait_reconnect_backoff(self, stop: Event, error: Exception) -> bool:
        if self.on_disconnect is not None:
            self.on_disconnect(error)
        with self._lock:
            self._error = str(error)
            self._state = "backoff"
        if stop.wait(self._reconnect_delay):
            return True
        self._reconnect_delay = self.reconnect.next_delay(self._reconnect_delay)
        return False

    def _yield_connected_positions(
        self,
        rover: Rover,
        connection: int,
        stop: Event,
        *,
        interval: float,
        heading: bool,
        heading_tolerance: float,
    ) -> Iterator[RoverUpdate]:
        while not stop.is_set():
            position = rover.position(
                heading=heading,
                heading_tolerance=heading_tolerance,
            )
            now = monotonic()
            with self._lock:
                self._positions += 1
                self._last_position = now
            self._reconnect_delay = self.reconnect.initial_seconds
            yield RoverUpdate(position, connection, rover.stream.session_id, now)
            if stop.wait(interval):
                return

    def _fail(self, error: Exception) -> None:
        with self._lock:
            self._error = str(error)
            self._state = "failed"

    def _mark_stopped(self) -> None:
        with self._lock:
            if self._state != "failed":
                self._state = "stopped"

    def health(self) -> RoverSessionHealth:
        """Return receiver and correction state for the current connection."""
        with self._lock:
            rover = self._rover
            return RoverSessionHealth(
                self._state,
                self._attempts,
                self._connections,
                self._positions,
                self._last_position,
                self._error,
                None if rover is None else rover.stream.health(),
                None if rover is None else rover.correction_health(),
            )

    def positions(
        self,
        stop: Event,
        *,
        interval: float = 1.0,
        heading: bool = False,
        heading_tolerance: float = 0.5,
    ) -> Iterator[RoverUpdate]:
        """Yield positions until stopped, reconnecting failed receiver transports."""
        if isinstance(interval, bool) or not isfinite(interval) or interval <= 0:
            raise ValueError("interval must be finite and positive")
        if (
            isinstance(heading_tolerance, bool)
            or not isfinite(heading_tolerance)
            or heading_tolerance < 0
        ):
            raise ValueError("heading_tolerance must be finite and non-negative")
        self._require_idle()
        try:
            while not stop.is_set():
                self._begin_connection_attempt()
                try:
                    with self._connect() as (rover, connection):
                        yield from self._yield_connected_positions(
                            rover,
                            connection,
                            stop,
                            interval=interval,
                            heading=heading,
                            heading_tolerance=heading_tolerance,
                        )
                except ResponseTimeout:
                    raise
                except (TransportError, OSError) as error:
                    if self._wait_reconnect_backoff(stop, error):
                        break
        except Exception as error:
            self._fail(error)
            raise
        finally:
            self._mark_stopped()
