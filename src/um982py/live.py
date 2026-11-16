"""Reconnect a receiver and deliver timestamped GGA position updates."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from threading import Event, Lock
from typing import TYPE_CHECKING

from um982py.errors import ProtocolError, ResponseTimeout, TransportError
from um982py.messages import Sentence
from um982py.messages.navigation import Fix
from um982py.ntrip import ReconnectPolicy

if TYPE_CHECKING:
    from um982py.receiver import Receiver
    from um982py.streaming import ReceiverStream

__all__ = ["LiveHealth", "PositionSession", "PositionSubscription", "PositionUpdate"]


@dataclass(frozen=True, slots=True)
class PositionUpdate:
    """A GGA fix and its host frame-completion time.

    The full frame has been decoded at this time; it can have spent time in
    receiver or operating-system buffers before it was read.
    """

    fix: Fix
    received_at: datetime
    received_monotonic: float
    previous_quality: int | None
    connection: int

    @property
    def quality_changed(self) -> bool:
        return (
            self.previous_quality is not None
            and self.fix.quality != self.previous_quality
        )


@dataclass(frozen=True, slots=True)
class LiveHealth:
    state: str
    attempts: int
    connections: int
    fixes: int
    malformed_fixes: int
    last_fix_monotonic: float | None
    last_error: str | None


class PositionSubscription:
    """Adapt an existing ReceiverStream subscription into GGA position updates.

    This borrows the worker, configures no receiver output and does not reconnect.
    Closing releases only this subscription. For a bounded position stream,
    start with ``Receiver.stream_positions()``.
    """

    def __init__(self, stream: ReceiverStream, *, capacity: int = 1024) -> None:
        self.stream = stream
        self._subscription = stream.subscribe(
            capacity=capacity, sentence_kinds=frozenset({"GGA"})
        )
        self._previous: int | None = None
        self._closed = False

    @property
    def dropped(self) -> int:
        return self._subscription.dropped

    def get(self, timeout: float | None = None) -> PositionUpdate:
        event = self._subscription.get_event(timeout)
        fix = Fix.from_message(event.message)
        update = PositionUpdate(
            fix, event.received_at, event.received_monotonic, self._previous, 1
        )
        self._previous = fix.quality
        return update

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.stream.unsubscribe(self._subscription)

    def __enter__(self) -> PositionSubscription:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class PositionSession:
    """Own successive receiver connections and read their already-emitted GGA fixes.

    Use this for a passive GGA reader that reconnects. For BESTNAV positions
    with optional NTRIP and heading, use ``rover_session.RoverSession``.

    The factory opens a fresh receiver for each connection. If supplied, the
    configure callback runs after every connection and can enable GGA output.
    It is responsible for any receiver settings it changes. The optional
    ``on_disconnect`` callback runs before a reconnection attempt.

    Only transport errors trigger a reconnect. The stop event interrupts the
    backoff and is checked within ``poll_seconds`` when the receiver is idle.
    """

    def __init__(
        self,
        receiver_factory: Callable[[], Receiver],
        *,
        configure: Callable[[Receiver], None] | None = None,
        on_disconnect: Callable[[Exception], None] | None = None,
        poll_seconds: float = 1.0,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        if not callable(receiver_factory):
            raise TypeError("receiver_factory must be callable")
        if configure is not None and not callable(configure):
            raise TypeError("configure must be callable")
        if on_disconnect is not None and not callable(on_disconnect):
            raise TypeError("on_disconnect must be callable")
        if (
            isinstance(poll_seconds, bool)
            or not isfinite(poll_seconds)
            or not 0 < poll_seconds <= 60
        ):
            raise ValueError("poll_seconds must be finite, positive and at most 60")
        self.receiver_factory = receiver_factory
        self.configure = configure
        self.on_disconnect = on_disconnect
        self.poll_seconds = poll_seconds
        self.reconnect = reconnect or ReconnectPolicy()
        self._lock = Lock()
        self._state = "idle"
        self._attempts = 0
        self._connections = 0
        self._fixes = 0
        self._malformed = 0
        self._last_fix: float | None = None
        self._error: str | None = None

    def health(self) -> LiveHealth:
        with self._lock:
            return LiveHealth(
                self._state,
                self._attempts,
                self._connections,
                self._fixes,
                self._malformed,
                self._last_fix,
                self._error,
            )

    def positions(self, stop: Event) -> Generator[PositionUpdate, None, None]:
        """Yield fixes until stopped, and close the iterator if you stop early."""
        with self._lock:
            if self._state != "idle":
                raise RuntimeError("session can only be run once")
            self._state = "connecting"
        delay = self.reconnect.initial_seconds
        previous: int | None = None
        try:
            while not stop.is_set():
                with self._lock:
                    self._state = "connecting"
                    self._attempts += 1
                try:
                    with self.receiver_factory() as receiver:
                        if self.configure is not None:
                            self.configure(receiver)
                        with self._lock:
                            self._connections += 1
                            connection = self._connections
                            self._state = "connected"
                        while not stop.is_set():
                            try:
                                frame = receiver._receive_timed(
                                    timeout=self.poll_seconds
                                )
                            except ResponseTimeout:
                                continue
                            message = frame.message
                            if (
                                not isinstance(message, Sentence)
                                or message.kind != "GGA"
                            ):
                                continue
                            try:
                                fix = Fix.from_message(message)
                            except ProtocolError:
                                with self._lock:
                                    self._malformed += 1
                                continue
                            now = frame.received_monotonic
                            with self._lock:
                                self._fixes += 1
                                self._last_fix = now
                            update = PositionUpdate(
                                fix, frame.received_at, now, previous, connection
                            )
                            previous = fix.quality
                            delay = self.reconnect.initial_seconds
                            yield update
                except (TransportError, OSError) as error:
                    if self.on_disconnect is not None:
                        self.on_disconnect(error)
                    with self._lock:
                        self._error = str(error)
                        self._state = "backoff"
                    if stop.wait(delay):
                        break
                    delay = self.reconnect.next_delay(delay)
        except Exception as error:
            with self._lock:
                self._error = str(error)
                self._state = "failed"
            raise
        else:
            with self._lock:
                self._state = "stopped"
        finally:
            with self._lock:
                if self._state != "failed":
                    self._state = "stopped"
