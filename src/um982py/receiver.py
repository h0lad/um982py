"""Receiver transactions and message streaming."""

from collections import deque
from collections.abc import Callable, Iterator
from math import isfinite
from threading import Event, RLock
from time import monotonic, sleep
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit

from um982py.antenna import AntennaLog, antenna_log
from um982py.augmentation import AugmentationState, enable_augmentation
from um982py.commands import Log, queries
from um982py.commands.configuration.receiver import (
    SignalGroup,
    current_signal_group,
)
from um982py.commands.core import Command, normalize
from um982py.errors import (
    BufferOverflow,
    CommandRejected,
    ResponseTimeout,
    TransportClosed,
)
from um982py.measurement import RangeSample, range_samples
from um982py.messages.frames import CommandResponse, Message, RtcmMessage
from um982py.messages.navigation import BestNavigation, Fix, Heading
from um982py.messages.record import Record
from um982py.messages.version import Version
from um982py.ppp import PppService, PppSession, _start_ppp
from um982py.protocol.decoder import StreamDecoder
from um982py.receiver_models import (
    FirmwareInfo,
    LogList,
    PerformanceStatus,
    ReceiverConfig,
    ReceiverSystemStatus,
    parse_configuration,
)
from um982py.receiver_queries import (
    firmware_info,
    log_list,
    performance_status,
    receiver_system_status,
)
from um982py.satellites import Satellite, satellites_from_record
from um982py.transports.base import Transport
from um982py.transports.serial import SerialTransport
from um982py.transports.tcp import TcpTransport


def _timeout(value: float) -> float:
    if not isfinite(value) or value <= 0:
        raise ValueError("timeout must be finite and positive")
    return value


class Receiver:
    def __init__(
        self,
        transport: Transport,
        *,
        timeout: float = 3,
        checksummed: bool = False,
        queue_limit: int = 4096,
        decoder: StreamDecoder | None = None,
    ) -> None:
        if queue_limit < 1:
            raise ValueError("queue_limit must be positive")
        self.transport = transport
        self.timeout = _timeout(timeout)
        self.checksummed = checksummed
        self.queue_limit = queue_limit
        self.decoder = decoder if decoder is not None else StreamDecoder()
        self._incoming: deque[Message] = deque()
        self._backlog: deque[Message] = deque()
        self._lock = RLock()
        self._closed = False
        self._in_poll_callback = False

    @classmethod
    def serial(cls, port: str, baudrate: int = 115200, *, timeout: float = 3) -> Self:
        _timeout(timeout)
        return cls(SerialTransport(port, baudrate), timeout=timeout)

    @classmethod
    def tcp(cls, host: str, port: int, *, timeout: float = 3) -> Self:
        _timeout(timeout)
        return cls(TcpTransport(host, port, timeout=timeout), timeout=timeout)

    @classmethod
    def connect(
        cls, target: str, baudrate: int = 115200, *, timeout: float = 3
    ) -> Self:
        if target.lower().startswith("tcp://"):
            try:
                address = urlsplit(target)
                host, port = address.hostname, address.port
            except ValueError as error:
                raise ValueError("TCP target must be tcp://host:port") from error
            if (
                not host
                or port is None
                or port < 1
                or address.username is not None
                or address.password is not None
                or address.path
                or address.query
                or address.fragment
            ):
                raise ValueError("TCP target must be tcp://host:port")
            return cls.tcp(host, port, timeout=timeout)
        return cls.serial(target, baudrate, timeout=timeout)

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._in_poll_callback:
                raise RuntimeError("receiver operations are unavailable in on_message")
            if not self._closed:
                self.transport.close()
                self._closed = True

    def execute[T](self, command: Command[T], *, timeout: float | None = None) -> T:
        duration = self.timeout if timeout is None else _timeout(timeout)
        with self._lock:
            deadline = monotonic() + duration
            self._start(command, duration)
            while True:
                message = self._next(deadline)
                if message is None:
                    raise ResponseTimeout(f"Timed out waiting for {command.text}")
                self._check_rejection(command.text, message)
                if command.matches(message):
                    return command.decode(message)
                self._save(message)

    def collect[T](
        self,
        command: Command[T],
        *,
        timeout: float | None = None,
        quiet: float = 0.15,
    ) -> tuple[T, ...]:
        duration = self.timeout if timeout is None else _timeout(timeout)
        _timeout(quiet)
        with self._lock:
            deadline = monotonic() + duration
            self._start(command, duration)
            values: list[T] = []
            idle_deadline = deadline
            while True:
                message = self._next(min(deadline, idle_deadline))
                if message is None:
                    if not values:
                        raise ResponseTimeout(f"No records for {command.text}")
                    return tuple(values)
                self._check_rejection(command.text, message)
                if command.matches(message):
                    values.append(command.decode(message))
                    idle_deadline = monotonic() + quiet
                else:
                    self._save(message)

    def receive(self, *, timeout: float | None = None) -> Message:
        duration = self.timeout if timeout is None else _timeout(timeout)
        with self._lock:
            self._check_open()
            if self._backlog:
                return self._backlog.popleft()
            message = self._next(monotonic() + duration)
            if message is None:
                raise ResponseTimeout("No receiver message before timeout")
            return message

    def drain_pending(self) -> tuple[Message, ...]:
        """Return the messages currently in the queue."""
        with self._lock:
            self._check_open()
            messages = (*self._backlog, *self._incoming)
            self._backlog.clear()
            self._incoming.clear()
            return messages

    def messages(self) -> Iterator[Message]:
        while True:
            yield self.receive()

    def version(self, *, binary: bool = False) -> Version:
        return self.execute(queries.version(binary=binary))

    def configuration(self) -> ReceiverConfig:
        """Query and parse the current receiver configuration."""
        return parse_configuration(self.collect(queries.configuration()))

    def signal_group(self) -> SignalGroup:
        """Query the active master and slave signal group."""
        return self.execute(current_signal_group())

    def log_list(self) -> LogList:
        """Query the active log subscriptions on all ports."""
        return self.execute(log_list())

    def firmware_info(self, *, binary: bool = False) -> FirmwareInfo:
        """Query extended enclosure and secondary firmware metadata."""
        return self.execute(firmware_info(binary=binary))

    def performance_status(self) -> PerformanceStatus:
        """Query RTOS task CPU utilization and NVM loop counters."""
        return self.execute(performance_status())

    def system_status(self) -> ReceiverSystemStatus:
        """Query hardware clock frequencies and component build versions."""
        return self.execute(receiver_system_status())

    def fix(self, *, antenna: int = 1) -> Fix:
        """Query a one-shot GGA position fix for the selected antenna."""
        return self.execute(queries.fix(antenna=antenna))

    def positions(
        self,
        *,
        interval: float = 1,
        antenna: int = 1,
        stop: Event | None = None,
        on_message: Callable[[Message], None] | None = None,
    ) -> Iterator[Fix]:
        """Poll GGA positions until the caller stops iterating.

        Each query uses the receiver timeout. The interval is the pause between
        queries, and the receiver remains open when iteration stops. Other
        messages received during a query go to ``on_message`` or are discarded.
        Messages already queued before the query remain available to ``receive``.
        The callback runs within the transaction and must not use the receiver.
        """
        if isinstance(interval, bool) or not isfinite(interval) or interval <= 0:
            raise ValueError("interval must be finite and positive")
        if antenna not in (1, 2):
            raise ValueError("antenna must be 1 or 2")
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable")

        def poll() -> Iterator[Fix]:
            while stop is None or not stop.is_set():
                yield self._poll_query(queries.fix(antenna=antenna), on_message)
                if stop is None:
                    sleep(interval)
                elif stop.wait(interval):
                    return

        return poll()

    def best_navigation(
        self, *, binary: bool = False, antenna: int = 1
    ) -> BestNavigation:
        """Query the best position and velocity solution for the selected antenna."""
        return self.execute(queries.best_navigation(binary=binary, antenna=antenna))

    def heading(self) -> Heading:
        """Query a one-shot dual-antenna THS heading solution."""
        return self.execute(queries.heading())

    def satellites(self) -> tuple[Satellite, ...]:
        """Return tracked satellites with named constellations and signals."""
        return satellites_from_record(self.read_log(Log.SATSINFO))

    def start_ppp(self, *, service: PppService = "E6-HAS") -> PppSession:
        """Configure a satellite PPP service and read its solutions.

        An active ONLY setting for the requested service is retained.
        """
        return _start_ppp(self, service=service)

    def read_log(
        self,
        log: Log | AntennaLog,
        *,
        binary: bool | None = None,
        antenna: str = "primary",
    ) -> Record:
        """Read one log, preferring binary when its format is supported.

        Pass ``binary=True`` or ``False`` to require a particular wire format.
        """
        selected = antenna_log(log, antenna)
        if binary is None:
            try:
                selected.wire_name(binary=True)
            except ValueError:
                binary = False
            else:
                binary = True
        return self.execute(selected.read(binary=binary))

    def range_samples(
        self,
        *,
        antenna: str = "primary",
        systems: tuple[int, ...] | None = None,
        signals: tuple[int, ...] | None = None,
    ) -> tuple[RangeSample, ...]:
        """Read one RANGE or RANGEH epoch and return observations in SI units."""
        record = self.read_log(Log.RANGE, binary=True, antenna=antenna)
        return range_samples(record, systems=systems, signals=signals)

    def enable_augmentation(self, *, persist: bool = False) -> AugmentationState:
        """Enable high-accuracy signal group, SBAS, E6-HAS, B2b-PPP and MMP."""
        return enable_augmentation(self, persist=persist)

    def send_correction(self, message: RtcmMessage) -> None:
        with self._lock:
            self._check_open()
            self.transport.write(message.raw, self.timeout)

    def send[T](self, command: Command[T]) -> None:
        with self._lock:
            self._check_open()
            self.transport.write(
                command.encode(checksummed=self.checksummed), self.timeout
            )

    def _start[T](self, command: Command[T], duration: float) -> None:
        self._check_open()
        while self._incoming:
            self._save(self._incoming.popleft())
        self.transport.write(command.encode(checksummed=self.checksummed), duration)

    def _poll_query[T](
        self, command: Command[T], on_message: Callable[[Message], None] | None = None
    ) -> T:
        """Run a polling query while routing other new messages to the callback."""
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable")
        with self._lock:
            self._check_open()
            prior_bytes = len(self.decoder.pending)
            if (
                prior_bytes
                and len(self._incoming) + len(self._backlog) >= self.queue_limit
            ):
                raise BufferOverflow("Receiver queue full; consume messages")
            deadline = monotonic() + self.timeout
            self._start(command, self.timeout)
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ResponseTimeout(f"Timed out waiting for {command.text}")
                chunk = self.transport.read(65536, remaining)
                newly_completed: list[Message] = []
                if prior_bytes:
                    for index, byte in enumerate(chunk):
                        discarded = self.decoder.discarded_bytes
                        completed = self.decoder.feed(bytes((byte,)))
                        prior_bytes = max(
                            0,
                            prior_bytes - (self.decoder.discarded_bytes - discarded),
                        )
                        for message in completed:
                            if prior_bytes:
                                prior_bytes = max(0, prior_bytes - len(message.raw))
                                self._save(message)
                            else:
                                newly_completed.append(message)
                        if not prior_bytes:
                            chunk = chunk[index + 1 :]
                            break
                    else:
                        continue
                messages = (*newly_completed, *self.decoder.feed(chunk))
                found = False
                result: T | None = None
                failure: Exception | None = None
                for message in messages:
                    if failure is None:
                        try:
                            self._check_rejection(command.text, message)
                            if not found and command.matches(message):
                                result = command.decode(message)
                                found = True
                                continue
                        except Exception as error:
                            failure = error
                            if not found:
                                continue
                    if on_message is not None:
                        self._in_poll_callback = True
                        try:
                            on_message(message)
                        finally:
                            self._in_poll_callback = False
                if failure is not None:
                    raise failure
                if found:
                    return result  # type: ignore[return-value]

    def _next(self, deadline: float) -> Message | None:
        while True:
            if self._incoming:
                return self._incoming.popleft()
            if monotonic() >= deadline:
                return None
            chunk = self.transport.read(65536, max(0, deadline - monotonic()))
            self._incoming.extend(self.decoder.feed(chunk))
            if len(self._incoming) + len(self._backlog) > self.queue_limit:
                raise BufferOverflow("Receiver queue full; consume messages")

    def _save(self, message: Message) -> None:
        if len(self._incoming) + len(self._backlog) >= self.queue_limit:
            raise BufferOverflow("Receiver queue full; consume messages")
        self._backlog.append(message)

    def _check_open(self) -> None:
        if self._in_poll_callback:
            raise RuntimeError("receiver operations are unavailable in on_message")
        if self._closed:
            raise TransportClosed("Receiver is closed")

    @staticmethod
    def _check_rejection(command: str, message: Message) -> None:
        if (
            isinstance(message, CommandResponse)
            and normalize(message.command) == normalize(command)
            and not message.accepted
        ):
            raise CommandRejected(command, message.status)
