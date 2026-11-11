"""Single-owner receiver worker with bounded message subscriptions."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from types import TracebackType
from typing import TYPE_CHECKING, Self

from um982py.errors import ResponseTimeout, TransportClosed
from um982py.measurement import gps_epoch
from um982py.messages import Message, RtcmMessage, Sentence

if TYPE_CHECKING:
    from collections.abc import Callable

    from um982py.antenna import AntennaLog
    from um982py.commands import Log
    from um982py.commands.core import Command
    from um982py.commands.types import Port
    from um982py.messages import CommandResponse
    from um982py.receiver import Receiver


@dataclass(frozen=True, slots=True)
class StreamEvent:
    message: Message
    received_at: datetime
    received_monotonic: float


class Subscription:
    """A bounded message queue whose ``dropped`` count records discarded messages."""

    def __init__(
        self, capacity: int, sentence_kinds: frozenset[str] | None = None
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        if sentence_kinds is not None and not sentence_kinds:
            raise ValueError("sentence_kinds must not be empty")
        self._sentence_kinds = sentence_kinds
        self._queue: Queue[StreamEvent] = Queue(capacity)
        self._lock = Lock()
        self._dropped = 0
        self._closed = Event()

    def get(self, timeout: float | None = None) -> Message:
        """Read a message, raising Empty on timeout or TransportClosed at end."""
        return self.get_event(timeout).message

    def get_event(self, timeout: float | None = None) -> StreamEvent:
        """Read a message with its host dispatch time."""
        if timeout is not None and (not isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and non-negative")
        deadline = None if timeout is None else monotonic() + timeout
        while True:
            if self._closed.is_set() and self._queue.empty():
                raise TransportClosed("subscription closed")
            remaining = None if deadline is None else max(0.0, deadline - monotonic())
            try:
                return self._queue.get(
                    timeout=0.1 if remaining is None else min(remaining, 0.1)
                )
            except Empty:
                if deadline is not None and monotonic() >= deadline:
                    raise

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _put(self, event: StreamEvent) -> None:
        if self._sentence_kinds is not None and (
            not isinstance(event.message, Sentence)
            or event.message.kind not in self._sentence_kinds
        ):
            return
        try:
            self._queue.put_nowait(event)
        except Full:
            with self._lock:
                self._dropped += 1

    def _finish(self) -> None:
        self._closed.set()


@dataclass(frozen=True, slots=True)
class StreamHealth:
    running: bool
    messages: int
    last_arrival_monotonic: float | None
    last_receiver_gps_seconds: float | None
    subscription_drops: int
    discarded_bytes: int
    recent_decoder_errors: tuple[str, ...]
    failure: str | None


class ReceiverStream:
    """Dispatch receiver data and serialize commands in one background thread.

    Add subscriptions before calling ``start()``. The worker owns the receiver
    while it is running. Commands delay delivery until they finish. Closing
    waits for the current operation and can also close the receiver.
    """

    def __init__(
        self,
        receiver: Receiver,
        *,
        poll_seconds: float = 0.01,
        operation_limit: int = 256,
    ) -> None:
        if not 0 < poll_seconds <= 1:
            raise ValueError("poll_seconds must be greater than zero and at most one")
        if operation_limit < 1:
            raise ValueError("operation_limit must be positive")
        self.receiver = receiver
        self.poll_seconds = poll_seconds
        self._subscriptions: list[Subscription] = []
        self._retired_drops = 0
        self._lock = Lock()
        self._stop = Event()
        self._operations: Queue[tuple[Callable[[], object], Future[object]]] = Queue(
            operation_limit
        )
        self._thread: Thread | None = None
        self._messages = 0
        self._last_arrival: float | None = None
        self._last_epoch: float | None = None
        self._failure: BaseException | None = None
        self._discarded_bytes = 0
        self._decoder_errors: tuple[str, ...] = ()

    def subscribe(
        self, *, capacity: int = 1024, sentence_kinds: frozenset[str] | None = None
    ) -> Subscription:
        """Subscribe to all messages or only the selected NMEA sentence kinds."""
        subscription = Subscription(capacity, sentence_kinds)
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("stream is stopped")
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.remove(subscription)
            subscription._finish()
            self._retired_drops += subscription.dropped

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("stream already started")
            if self._stop.is_set():
                raise RuntimeError("stream is stopped")
            self._thread = Thread(target=self._run, name="um982py-stream", daemon=True)
            self._thread.start()

    def __enter__(self) -> Self:
        """Start the worker while leaving receiver ownership with the caller."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def execute[T](
        self, command: Command[T], *, timeout: float | None = None
    ) -> Future[T]:
        """Queue a command and return a future for its result or error."""
        return self._submit(lambda: self.receiver.execute(command, timeout=timeout))

    def set_output_rate(
        self,
        logs: Log | AntennaLog | Sequence[Log | AntennaLog],
        rate_hz: float,
        *,
        binary: bool | None = None,
        port: Port | None = None,
        verify: bool = False,
    ) -> Future[tuple[CommandResponse, ...]]:
        """Queue a receiver output-rate change and return its future."""
        selected = (
            tuple(logs)
            if isinstance(logs, Sequence) and not isinstance(logs, str)
            else logs
        )
        return self._submit(
            lambda: self.receiver.set_output_rate(
                selected, rate_hz, binary=binary, port=port, verify=verify
            )
        )

    def send_correction(self, message: RtcmMessage) -> Future[None]:
        return self._submit(lambda: self.receiver.send_correction(message))

    def _submit[T](self, operation: Callable[[], T]) -> Future[T]:
        future: Future[T] = Future()
        with self._lock:
            if self._thread is None or self._stop.is_set():
                raise RuntimeError("stream is not running")
            self._operations.put_nowait((operation, future))  # type: ignore[arg-type]
        return future

    def health(self) -> StreamHealth:
        with self._lock:
            return StreamHealth(
                running=self._thread is not None and not self._stop.is_set(),
                messages=self._messages,
                last_arrival_monotonic=self._last_arrival,
                last_receiver_gps_seconds=self._last_epoch,
                subscription_drops=self._retired_drops
                + sum(item.dropped for item in self._subscriptions),
                discarded_bytes=self._discarded_bytes,
                recent_decoder_errors=self._decoder_errors,
                failure=None if self._failure is None else repr(self._failure),
            )

    def close(self, *, close_receiver: bool = False) -> None:
        with self._lock:
            self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join()
        else:
            with self._lock:
                for subscription in self._subscriptions:
                    subscription._finish()
        if close_receiver:
            self.receiver.close()

    def _dispatch(self, message: Message) -> None:
        try:
            epoch = gps_epoch(message)
        except (ValueError, TypeError, AttributeError):
            epoch = None
        received = monotonic()
        event = StreamEvent(message, datetime.now(UTC), received)
        with self._lock:
            self._messages += 1
            self._last_arrival = received
            if epoch is not None:
                self._last_epoch = epoch
            for subscription in self._subscriptions:
                subscription._put(event)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    operation, future = self._operations.get_nowait()
                except Empty:
                    operation = None
                if operation is not None and future.set_running_or_notify_cancel():
                    try:
                        future.set_result(operation())
                    except Exception as error:
                        future.set_exception(error)
                for message in self.receiver.drain_pending():
                    self._dispatch(message)
                with suppress(ResponseTimeout):
                    self._dispatch(self.receiver.receive(timeout=self.poll_seconds))
                with self._lock:
                    self._discarded_bytes = self.receiver.decoder.discarded_bytes
                    self._decoder_errors = tuple(map(str, self.receiver.decoder.errors))
        except Exception as error:
            with self._lock:
                self._failure = error
        finally:
            with self._lock:
                self._stop.set()
                for subscription in self._subscriptions:
                    subscription._finish()
            while True:
                try:
                    _, future = self._operations.get_nowait()
                except Empty:
                    break
                if future.set_running_or_notify_cancel():
                    future.set_exception(TransportClosed("receiver stream stopped"))
