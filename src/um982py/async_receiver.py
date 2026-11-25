"""Use the receiver from asyncio while keeping the event loop responsive."""

import asyncio
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Sequence,
)
from contextlib import asynccontextmanager, suppress
from functools import wraps
from sys import exception
from types import TracebackType
from typing import Any, Concatenate, Self

from um982py._polling import poll_async, validate_callback, validate_interval
from um982py.antenna import AntennaLog
from um982py.async_ppp import AsyncPppSession
from um982py.commands import Log, queries
from um982py.commands.core import Command
from um982py.commands.types import Port
from um982py.messages.frames import CommandResponse, Message
from um982py.messages.navigation import Fix
from um982py.ppp import PppService
from um982py.receiver import Receiver


def _threaded[**P, R](
    method: Callable[Concatenate[Receiver, P], R],
) -> Callable[Concatenate[AsyncReceiver, P], Coroutine[Any, Any, R]]:
    """Expose a blocking ``Receiver`` method as a coroutine with its signature.

    The call runs in a worker thread under the receiver's transaction lock.
    It looks the method up on the wrapped receiver at call time, so subclass
    overrides apply.
    """
    name = method.__name__

    @wraps(method)
    async def call(self: AsyncReceiver, /, *args: P.args, **kwargs: P.kwargs) -> R:
        bound: Callable[P, R] = getattr(self.receiver, name)
        return await self._run(lambda: bound(*args, **kwargs))

    return call


async def _wait_for_io[T](task: asyncio.Task[T]) -> T:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


class AsyncReceiver:
    def __init__(self, receiver: Receiver) -> None:
        self.receiver = receiver
        self._lock = asyncio.Lock()

    @classmethod
    async def serial(
        cls, port: str, baudrate: int = 115200, *, timeout: float = 3
    ) -> Self:
        return await cls._connect(
            lambda: Receiver.serial(port, baudrate, timeout=timeout)
        )

    @classmethod
    async def tcp(cls, host: str, port: int, *, timeout: float = 3) -> Self:
        return await cls._connect(lambda: Receiver.tcp(host, port, timeout=timeout))

    @classmethod
    async def connect(
        cls, target: str, baudrate: int = 115200, *, timeout: float = 3
    ) -> Self:
        return await cls._connect(
            lambda: Receiver.connect(target, baudrate, timeout=timeout)
        )

    @classmethod
    async def _connect(cls, operation: Callable[[], Receiver]) -> Self:
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return cls(await asyncio.shield(task))
        except asyncio.CancelledError as cancellation:
            with suppress(Exception):
                receiver = await _wait_for_io(task)
                await _wait_for_io(
                    asyncio.create_task(asyncio.to_thread(receiver.close))
                )
            raise cancellation

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    close = _threaded(Receiver.close)

    async def execute[T](
        self,
        command: Command[T],
        *,
        timeout: float | None = None,
        accept: Callable[[T], bool] | None = None,
    ) -> T:
        return await self._run(
            lambda: self.receiver.execute(command, timeout=timeout, accept=accept)
        )

    async def collect[T](
        self, command: Command[T], *, timeout: float | None = None, quiet: float = 0.15
    ) -> tuple[T, ...]:
        return await self._run(
            lambda: self.receiver.collect(command, timeout=timeout, quiet=quiet)
        )

    receive = _threaded(Receiver.receive)

    drain_pending = _threaded(Receiver.drain_pending)

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            yield await self.receive()

    version = _threaded(Receiver.version)

    configuration = _threaded(Receiver.configuration)

    signal_group = _threaded(Receiver.signal_group)

    log_list = _threaded(Receiver.log_list)

    async def set_output_rate(
        self,
        logs: Log | AntennaLog | Sequence[Log | AntennaLog],
        rate_hz: float,
        *,
        binary: bool | None = None,
        port: Port | None = None,
        verify: bool = False,
    ) -> tuple[CommandResponse, ...]:
        """Configure log output rates through the receiver transaction lock."""
        try:
            return await self._run(
                lambda: self.receiver.set_output_rate(
                    logs, rate_hz, binary=binary, port=port, verify=verify
                )
            )
        except asyncio.CancelledError as error:
            error.add_note("Output settings may have changed before cancellation.")
            raise

    firmware_info = _threaded(Receiver.firmware_info)

    performance_status = _threaded(Receiver.performance_status)

    system_status = _threaded(Receiver.system_status)

    pps_status = _threaded(Receiver.pps_status)

    spoof_info = _threaded(Receiver.spoof_info)

    fix = _threaded(Receiver.fix)

    async def poll_positions(
        self,
        *,
        interval: float = 1,
        antenna: int = 1,
        stop: asyncio.Event | None = None,
        on_message: Callable[[Message], None] | None = None,
    ) -> AsyncIterator[Fix]:
        """Poll GGA positions.

        Other messages received during a query go to ``on_message`` or are
        discarded. Previously queued messages remain available to ``receive``.
        The callback runs in the worker thread and must not use the receiver.
        """
        validate_interval(interval)
        if type(antenna) is not int or antenna not in (1, 2):
            raise ValueError("antenna must be 1 or 2")
        validate_callback(on_message)
        async for fix in poll_async(
            lambda: self._run(
                lambda: self.receiver._poll_query(
                    queries.fix(antenna=antenna), on_message
                )
            ),
            interval,
            stop,
        ):
            yield fix

    @asynccontextmanager
    async def stream_positions(
        self, *, duration: float, rate_hz: float = 1, antenna: int = 1
    ) -> AsyncIterator[AsyncIterator[Fix]]:
        stream = self.receiver.stream_positions(
            duration=duration, rate_hz=rate_hz, antenna=antenna
        )
        positions = stream.__enter__()

        async def receive_positions() -> AsyncGenerator[Fix]:
            while True:
                item = await self._run(lambda: next(positions, None))
                if item is None:
                    return
                yield item

        iterator = receive_positions()
        try:
            yield iterator
        finally:
            error = exception()
            try:
                await iterator.aclose()
            finally:
                if error is None:
                    await self._run(lambda: stream.__exit__(None, None, None))
                else:
                    await self._run(
                        lambda: stream.__exit__(type(error), error, error.__traceback__)
                    )

    enable_augmentation = _threaded(Receiver.enable_augmentation)

    async def start_ppp(self, *, service: PppService = "E6-HAS") -> AsyncPppSession:
        """Configure and verify a PPP service for asynchronous position queries."""
        try:
            session = await self._run(lambda: self.receiver.start_ppp(service=service))
        except asyncio.CancelledError as error:
            error.add_note(
                "PPP setup may have changed receiver settings before cancellation."
            )
            raise
        return AsyncPppSession(self, session)

    best_navigation = _threaded(Receiver.best_navigation)

    heading = _threaded(Receiver.heading)

    satellites = _threaded(Receiver.satellites)

    read_log = _threaded(Receiver.read_log)

    range_samples = _threaded(Receiver.range_samples)

    async def _run[T](self, operation: Callable[[], T]) -> T:
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError as cancellation:
                with suppress(Exception):
                    await _wait_for_io(task)
                raise cancellation
