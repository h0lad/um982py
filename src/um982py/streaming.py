"""Single-owner receiver worker with bounded message subscriptions.

All receiver operations must go through the worker while it is running. Command
responses are consumed by the command; other messages are dispatched to every
subscription. Slow subscriptions drop new messages and count each drop.
"""

from __future__ import annotations

from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING

from um982py.errors import ResponseTimeout, TransportClosed
from um982py.measurement import gps_epoch
from um982py.messages import Message, RtcmMessage

if TYPE_CHECKING:
    from collections.abc import Callable

    from um982py.commands.core import Command
    from um982py.receiver import Receiver


class Subscription:
    """A bounded FIFO. ``dropped`` counts messages discarded while full."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._queue: Queue[Message] = Queue(capacity)
        self._lock = Lock()
        self._dropped = 0

    def get(self, timeout: float | None = None) -> Message:
        """Read one message, raising ``queue.Empty`` when the timeout expires."""
        return self._queue.get(timeout=timeout)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _put(self, message: Message) -> None:
        try:
            self._queue.put_nowait(message)
        except Full:
            with self._lock:
                self._dropped += 1


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

    Start with ``start()`` after adding subscriptions. Directly using the wrapped
    receiver concurrently is unsupported. A command can delay stream delivery
    until it completes; command timeouts should be kept short. Closing waits for
    the current receiver operation, then optionally closes the receiver.
    """

    def __init__(
        self,
        receiver: Receiver,
        *,
        poll_seconds: float = 0.05,
        operation_limit: int = 256,
    ) -> None:
        if not 0 < poll_seconds <= 1:
            raise ValueError("poll_seconds must be greater than zero and at most one")
        if operation_limit < 1:
            raise ValueError("operation_limit must be positive")
        self.receiver = receiver
        self.poll_seconds = poll_seconds
        self._subscriptions: list[Subscription] = []
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

    def subscribe(self, *, capacity: int = 1024) -> Subscription:
        subscription = Subscription(capacity)
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.remove(subscription)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("stream already started")
            self._thread = Thread(target=self._run, name="um982py-stream", daemon=True)
            self._thread.start()

    def execute[T](
        self, command: Command[T], *, timeout: float | None = None
    ) -> Future[T]:
        """Queue a command; its future receives the result or command error."""
        return self._submit(lambda: self.receiver.execute(command, timeout=timeout))

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
                subscription_drops=sum(item.dropped for item in self._subscriptions),
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
        if close_receiver:
            self.receiver.close()

    def _dispatch(self, message: Message) -> None:
        try:
            epoch = gps_epoch(message)
        except (ValueError, TypeError, AttributeError):
            epoch = None
        with self._lock:
            self._messages += 1
            self._last_arrival = monotonic()
            if epoch is not None:
                self._last_epoch = epoch
            for subscription in self._subscriptions:
                subscription._put(message)

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
            while True:
                try:
                    _, future = self._operations.get_nowait()
                except Empty:
                    break
                if not future.cancelled():
                    future.set_exception(TransportClosed("receiver stream stopped"))
