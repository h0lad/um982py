"""Use the receiver from asyncio while keeping the event loop responsive."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from math import isfinite
from types import TracebackType
from typing import Self

from um982py.antenna import AntennaLog
from um982py.async_ppp import AsyncPppSession
from um982py.augmentation import AugmentationState
from um982py.commands import Log, queries
from um982py.commands.configuration.receiver import SignalGroup
from um982py.commands.core import Command
from um982py.measurement import RangeSample
from um982py.messages.frames import Message
from um982py.messages.navigation import BestNavigation, Fix, Heading
from um982py.messages.record import Record
from um982py.messages.version import Version
from um982py.ppp import PppService
from um982py.receiver import Receiver
from um982py.receiver_models import (
    FirmwareInfo,
    LogList,
    PerformanceStatus,
    ReceiverConfig,
    ReceiverSystemStatus,
)
from um982py.satellites import Satellite


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

    async def close(self) -> None:
        await self._run(self.receiver.close)

    async def execute[T](
        self, command: Command[T], *, timeout: float | None = None
    ) -> T:
        return await self._run(lambda: self.receiver.execute(command, timeout=timeout))

    async def collect[T](
        self, command: Command[T], *, timeout: float | None = None, quiet: float = 0.15
    ) -> tuple[T, ...]:
        return await self._run(
            lambda: self.receiver.collect(command, timeout=timeout, quiet=quiet)
        )

    async def receive(self, *, timeout: float | None = None) -> Message:
        return await self._run(lambda: self.receiver.receive(timeout=timeout))

    async def drain_pending(self) -> tuple[Message, ...]:
        """Return the messages currently in the queue."""
        return await self._run(self.receiver.drain_pending)

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            yield await self.receive()

    async def version(self, *, binary: bool = False) -> Version:
        return await self._run(lambda: self.receiver.version(binary=binary))

    async def configuration(self) -> ReceiverConfig:
        """Query and parse the current receiver configuration."""
        return await self._run(self.receiver.configuration)

    async def signal_group(self) -> SignalGroup:
        """Query the active master and slave signal group."""
        return await self._run(self.receiver.signal_group)

    async def log_list(self) -> LogList:
        """Query the active log subscriptions."""
        return await self._run(self.receiver.log_list)

    async def firmware_info(self, *, binary: bool = False) -> FirmwareInfo:
        """Query extended firmware metadata."""
        return await self._run(lambda: self.receiver.firmware_info(binary=binary))

    async def performance_status(self) -> PerformanceStatus:
        """Query RTOS task CPU utilization."""
        return await self._run(self.receiver.performance_status)

    async def system_status(self) -> ReceiverSystemStatus:
        """Query hardware clock frequencies and component builds."""
        return await self._run(self.receiver.system_status)

    async def fix(self, *, antenna: int = 1) -> Fix:
        """Query a one-shot GGA position fix for the selected antenna."""
        return await self._run(lambda: self.receiver.fix(antenna=antenna))

    async def positions(
        self,
        *,
        interval: float = 1,
        antenna: int = 1,
        stop: asyncio.Event | None = None,
        on_message: Callable[[Message], None] | None = None,
    ) -> AsyncIterator[Fix]:
        """Poll GGA positions until the caller stops iterating.

        Other messages received during a query go to ``on_message`` or are
        discarded. Previously queued messages remain available to ``receive``.
        The callback runs in the worker thread and must not use the receiver.
        """
        if isinstance(interval, bool) or not isfinite(interval) or interval <= 0:
            raise ValueError("interval must be finite and positive")
        if antenna not in (1, 2):
            raise ValueError("antenna must be 1 or 2")
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable")
        while stop is None or not stop.is_set():
            yield await self._run(
                lambda: self.receiver._poll_query(
                    queries.fix(antenna=antenna), on_message
                )
            )
            if stop is None:
                await asyncio.sleep(interval)
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    continue
                return

    async def enable_augmentation(self, *, persist: bool = False) -> AugmentationState:
        """Enable the receiver's augmentation plan and report each result."""
        return await self._run(
            lambda: self.receiver.enable_augmentation(persist=persist)
        )

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

    async def best_navigation(
        self, *, binary: bool = False, antenna: int = 1
    ) -> BestNavigation:
        """Query the best position and velocity solution for the selected antenna."""
        return await self._run(
            lambda: self.receiver.best_navigation(binary=binary, antenna=antenna)
        )

    async def heading(self) -> Heading:
        """Query a one-shot dual-antenna THS heading solution."""
        return await self._run(self.receiver.heading)

    async def satellites(self) -> tuple[Satellite, ...]:
        """Return tracked satellites with named constellations and signals."""
        return await self._run(self.receiver.satellites)

    async def read_log(
        self,
        log: Log | AntennaLog,
        *,
        binary: bool | None = None,
        antenna: str = "primary",
    ) -> Record:
        """Read and decode a single log from the selected antenna."""
        return await self._run(
            lambda: self.receiver.read_log(log, binary=binary, antenna=antenna)
        )

    async def range_samples(
        self,
        *,
        antenna: str = "primary",
        systems: tuple[int, ...] | None = None,
        signals: tuple[int, ...] | None = None,
    ) -> tuple[RangeSample, ...]:
        """Read one RANGE or RANGEH epoch and return observations in SI units."""
        return await self._run(
            lambda: self.receiver.range_samples(
                antenna=antenna, systems=systems, signals=signals
            )
        )

    async def _run[T](self, operation: Callable[[], T]) -> T:
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError as cancellation:
                with suppress(Exception):
                    await _wait_for_io(task)
                raise cancellation
