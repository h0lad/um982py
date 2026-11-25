"""Reconnect a rover receiver while maintaining correction and stream status."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from math import isfinite
from threading import Event
from time import monotonic
from typing import Literal

from um982py.errors import ResponseTimeout
from um982py.ntrip import ReconnectPolicy, _Reconnecting
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


class RoverSession(_Reconnecting):
    """Own reconnecting BESTNAV polling, with optional NTRIP and matched heading.

    Use ``Rover`` for one receiver connection. This class owns a fresh receiver
    and rover worker per connection, exposing both connection and correction
    health. It polls positions rather than acting as a passive GGA
    subscription.

    The factory opens a new receiver each time. The optional configuration
    callback runs before the stream and NTRIP relay start on each connection.
    Transport errors retry with backoff, while protocol, configuration and
    fatal correction errors propagate. Caster reconnection is handled by the
    relay. Optional RTK and ADR reliability levels are applied on every
    receiver connection and are not restored.
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
        rtk_reliability_level: int | None = None,
        adr_reliability_level: int | None = None,
    ) -> None:
        if not callable(receiver_factory):
            raise TypeError("receiver_factory must be callable")
        if configure is not None and not callable(configure):
            raise TypeError("configure must be callable")
        if on_disconnect is not None and not callable(on_disconnect):
            raise TypeError("on_disconnect must be callable")
        if ntrip_url is None and (username is not None or password is not None):
            raise ValueError("credentials require an NTRIP URL")
        super().__init__(reconnect)
        self.receiver_factory = receiver_factory
        self.configure = configure
        self.on_disconnect = on_disconnect
        self.ntrip_url = ntrip_url
        self.username = username
        self.password = password
        self.ntrip_version = ntrip_version
        self.rtk_reliability_level = rtk_reliability_level
        self.adr_reliability_level = adr_reliability_level
        self._positions = 0
        self._last_position: float | None = None
        self._rover: Rover | None = None

    def _connected_positions(
        self,
        stop: Event,
        *,
        interval: float,
        heading: bool,
        heading_tolerance: float,
    ) -> Iterator[RoverUpdate]:
        """Poll positions from one receiver connection."""
        with self.receiver_factory() as receiver:
            if self.configure is not None:
                self.configure(receiver)
            with Rover(
                receiver,
                ntrip_url=self.ntrip_url,
                username=self.username,
                password=self.password,
                ntrip_version=self.ntrip_version,
                rtk_reliability_level=self.rtk_reliability_level,
                adr_reliability_level=self.adr_reliability_level,
            ) as rover:
                connection = self._connected()
                with self._lock:
                    self._rover = rover
                try:
                    while not stop.is_set():
                        position = rover.position(
                            heading=heading, heading_tolerance=heading_tolerance
                        )
                        now = monotonic()
                        with self._lock:
                            self._positions += 1
                            self._last_position = now
                        self._reset_backoff()
                        yield RoverUpdate(
                            position, connection, rover.stream.session_id, now
                        )
                        if stop.wait(interval):
                            return
                finally:
                    with self._lock:
                        self._rover = None

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
        yield from self._run_connections(
            stop,
            lambda: self._connected_positions(
                stop,
                interval=interval,
                heading=heading,
                heading_tolerance=heading_tolerance,
            ),
            self.on_disconnect,
            fatal=(ResponseTimeout,),
        )
