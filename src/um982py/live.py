"""Reconnect a receiver and deliver timestamped GGA position updates."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from queue import Empty
from threading import Event, Thread
from typing import TYPE_CHECKING, Literal

from um982py.errors import (
    ProtocolError,
    ResponseTimeout,
    TransportClosed,
)
from um982py.messages import Message, Sentence
from um982py.messages.navigation import Fix
from um982py.ntrip import ReconnectPolicy, _Reconnecting
from um982py.rtk_session import RtkHealth, RtkSession
from um982py.streaming import ReceiverStream

if TYPE_CHECKING:
    from um982py.receiver import Receiver

__all__ = ["LiveHealth", "PositionSession", "PositionSubscription", "PositionUpdate"]


@dataclass(frozen=True, slots=True)
class PositionUpdate:
    """A GGA fix and its host frame-completion time.

    The full frame has been decoded at this time, although it can have
    spent time in receiver or operating-system buffers before it was read.
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


class PositionSession(_Reconnecting):
    """Own successive receiver connections and read their already-emitted GGA fixes.

    Use this for a passive GGA reader that reconnects. For BESTNAV positions
    with optional NTRIP and heading, use ``rover_session.RoverSession``.

    The factory opens a fresh receiver for each connection. If supplied, the
    configure callback runs after every connection and can enable GGA output.
    It is responsible for any receiver settings it changes. The optional
    ``on_disconnect`` callback runs before a reconnection attempt. The optional
    ``on_message`` callback receives every decoded frame before GGA filtering.
    It must not raise or use the receiver. With ``subscribe=True``, each
    connection uses a ``ReceiverStream`` subscription instead of driving reads
    from this generator. Other decoded logs stay available to ``on_message``.
    An NTRIP URL with ``subscribe=True`` starts an ``RtkSession`` relay for each
    connection. ``correction_health()`` exposes its status.

    Only transport errors trigger a reconnect. The stop event interrupts the
    backoff and is checked within ``poll_seconds`` when the receiver is idle.
    """

    def __init__(
        self,
        receiver_factory: Callable[[], Receiver],
        *,
        configure: Callable[[Receiver], None] | None = None,
        on_disconnect: Callable[[Exception], None] | None = None,
        on_message: Callable[[Message], None] | None = None,
        subscribe: bool = False,
        ntrip_url: str | None = None,
        ntrip_username: str | None = None,
        ntrip_password: str | None = None,
        ntrip_version: Literal[1, 2] = 2,
        poll_seconds: float = 1.0,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        if not callable(receiver_factory):
            raise TypeError("receiver_factory must be callable")
        if configure is not None and not callable(configure):
            raise TypeError("configure must be callable")
        if on_disconnect is not None and not callable(on_disconnect):
            raise TypeError("on_disconnect must be callable")
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable")
        if (
            isinstance(poll_seconds, bool)
            or not isfinite(poll_seconds)
            or not 0 < poll_seconds <= 60
        ):
            raise ValueError("poll_seconds must be finite, positive and at most 60")
        super().__init__(reconnect)
        self.receiver_factory = receiver_factory
        self.configure = configure
        self.on_disconnect = on_disconnect
        self.on_message = on_message
        self.subscribe = subscribe
        self.ntrip_url = ntrip_url
        self.ntrip_username = ntrip_username
        self.ntrip_password = ntrip_password
        self.ntrip_version = ntrip_version
        self.poll_seconds = poll_seconds
        self._fixes = 0
        self._malformed = 0
        self._last_fix: float | None = None
        self._previous_quality: int | None = None
        self._rtk: RtkSession | None = None

    def _position_update(
        self,
        message: Message,
        received_at: datetime,
        received_monotonic: float,
        connection: int,
    ) -> PositionUpdate | None:
        """Pass a frame to ``on_message`` and turn a valid GGA into an update."""
        if self.on_message is not None:
            self.on_message(message)
        if not isinstance(message, Sentence) or message.kind != "GGA":
            return None
        try:
            fix = Fix.from_message(message)
        except ProtocolError:
            with self._lock:
                self._malformed += 1
            return None
        with self._lock:
            self._fixes += 1
            self._last_fix = received_monotonic
        update = PositionUpdate(
            fix, received_at, received_monotonic, self._previous_quality, connection
        )
        self._previous_quality = fix.quality
        self._reset_backoff()
        return update

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

    def correction_health(self) -> RtkHealth | None:
        """Return NTRIP relay status, or None when no URL was configured."""
        rtk = self._rtk
        return None if rtk is None else rtk.health()

    def _run_rtk(self, rtk: RtkSession, stop: Event) -> None:
        # The relay records terminal errors in its health snapshot.
        with suppress(Exception):
            rtk.run(stop)

    def _polled_connection(self, stop: Event) -> Iterator[PositionUpdate]:
        """Read fixes directly from one receiver connection."""
        with self.receiver_factory() as receiver:
            if self.configure is not None:
                self.configure(receiver)
            connection = self._connected()
            while not stop.is_set():
                try:
                    frame = receiver._receive_timed(timeout=self.poll_seconds)
                except ResponseTimeout:
                    continue
                update = self._position_update(
                    frame.message,
                    frame.received_at,
                    frame.received_monotonic,
                    connection,
                )
                if update is not None:
                    yield update

    def _subscribed_connection(self, stop: Event) -> Iterator[PositionUpdate]:
        """Read fixes from a ReceiverStream subscription on one connection."""
        with self.receiver_factory() as receiver:
            if self.configure is not None:
                self.configure(receiver)
            stream = ReceiverStream(receiver, poll_seconds=min(self.poll_seconds, 1.0))
            subscription = stream.subscribe(capacity=1024)
            with stream:
                connection = self._connected()
                relay_stop = Event()
                relay: Thread | None = None
                if self.ntrip_url is not None:
                    rtk = RtkSession.from_url(
                        stream,
                        self.ntrip_url,
                        username=self.ntrip_username,
                        password=self.ntrip_password,
                        version=self.ntrip_version,
                    )
                    with self._lock:
                        self._rtk = rtk
                    relay = Thread(
                        target=self._run_rtk, args=(rtk, relay_stop), daemon=True
                    )
                    relay.start()
                try:
                    while not stop.is_set():
                        try:
                            event = subscription.get_event(
                                timeout=min(self.poll_seconds, 0.2)
                            )
                        except Empty:
                            failure = stream.failure
                            if failure is not None:
                                raise failure from None
                            continue
                        except TransportClosed:
                            failure = stream.failure
                            if stop.is_set():
                                break
                            if isinstance(failure, BaseException):
                                raise failure from None
                            raise
                        update = self._position_update(
                            event.message,
                            event.received_at,
                            event.received_monotonic,
                            connection,
                        )
                        if update is not None:
                            yield update
                    failure = stream.failure
                    if failure is not None and not stop.is_set():
                        raise failure from None
                finally:
                    relay_stop.set()
                    if relay is not None:
                        relay.join()
                    with self._lock:
                        self._rtk = None

    def positions(self, stop: Event) -> Generator[PositionUpdate, None, None]:
        """Yield fixes until stopped, and close the iterator if you stop early."""
        connection = (
            self._subscribed_connection if self.subscribe else self._polled_connection
        )
        yield from self._run_connections(
            stop, lambda: connection(stop), self.on_disconnect
        )
