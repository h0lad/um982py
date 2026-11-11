"""Capture bounded live logs and replay wire transcripts."""

import math
import os
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from itertools import pairwise
from pathlib import Path
from time import monotonic
from typing import Protocol, overload

from um982py.antenna import AntennaLog
from um982py.commands import Log, Trigger, logging
from um982py.commands.core import Command
from um982py.errors import RecordingError, ResponseTimeout
from um982py.measurement import gps_epoch
from um982py.messages import CommandResponse, Message, Record
from um982py.protocol import StreamDecoder
from um982py.receiver import Receiver
from um982py.subscriptions import temporary_subscriptions
from um982py.transports.base import Transport

__all__ = [
    "GPS_FREQUENCIES",
    "AntennaLog",
    "DataLog",
    "InterruptedCapture",
    "RecordingTransport",
    "capture_live",
    "decode_records",
    "epoch_seconds",
    "gps_signals",
    "iter_frames",
    "latest_epoch",
    "load_records",
    "matcher",
    "read_frames",
    "receive_records",
    "record_epoch",
    "replay_receiver",
    "uniform_interval",
]

GPS_FREQUENCIES = {0: 1575.42e6, 9: 1227.60e6, 17: 1227.60e6, 14: 1176.45e6}

type DataLog = Log | AntennaLog


class InterruptedCapture(KeyboardInterrupt):
    """A cancelled read with the data received before cancellation."""

    def __init__(self, records: dict[str, tuple[Record, ...]]) -> None:
        super().__init__()
        self.records = records


def epoch_seconds(message: Message) -> float:
    """Return absolute GPS seconds from a supported data-frame header."""
    return gps_epoch(message)


def record_epoch(record: Record) -> float:
    """Return the receiver epoch from a decoded record's timestamp."""
    if record.message is None:
        raise ValueError(f"{record.name} record carries no receiver timestamp")
    return epoch_seconds(record.message)


def latest_epoch(records: Sequence[Record]) -> tuple[Record, ...]:
    """Return the constellation frames from the newest epoch only."""
    if not records:
        return ()
    newest = max(record_epoch(record) for record in records)
    by_system: dict[str, Record] = {}
    for record in records:
        if abs(record_epoch(record) - newest) < 1e-5:
            by_system[str(record.get("constellation", record.name))] = record
    return tuple(by_system.values())


def matcher(log: DataLog, binary: bool) -> Command[Message]:
    """Match a data log, including logs emitted only on events."""
    wire = log.wire if isinstance(log, AntennaLog) else log
    return logging.request(
        log.wire_name(binary=binary), message_id=wire.definition.message_id
    )


def _log_matchers(log: DataLog) -> tuple[Command[Message], ...]:
    requests = [matcher(log, False)]
    with suppress(ValueError):
        requests.append(matcher(log, True))
    return tuple(requests)


def decode_records(frames: Iterable[Message], log: DataLog) -> tuple[Record, ...]:
    """Decode matching ASCII and binary frames, raising on malformed bodies."""
    requests = _log_matchers(log)
    return tuple(
        log.decode(frame)
        for frame in frames
        if any(request.matches(frame) for request in requests)
    )


def gps_signals(
    record: Record,
    frequencies: Sequence[float] = (1575.42e6, 1176.45e6),
    *,
    phase: bool = True,
) -> tuple[tuple[Record, float], ...]:
    """Select GPS carriers by tracking status, defaulting to L1 C/A and L5."""
    if any(frequency not in GPS_FREQUENCIES.values() for frequency in frequencies):
        raise ValueError(
            "supported GPS carriers are 1575420000, 1227600000 and 1176450000 Hz"
        )
    selected: dict[tuple[int, float], Record] = {}
    for observation in record.records("observations"):
        status = observation.integer("tracking_status")
        frequency = GPS_FREQUENCIES.get((status >> 21) & 31)
        if (status >> 16) & 7 or frequency not in frequencies:
            continue
        if not status & (1 << 12) or (phase and not status & (1 << 10)):
            continue
        if frequency is None:
            continue
        key = observation.integer("prn"), frequency
        previous = selected.get(key)
        if previous is None or observation.real("cn0") > previous.real("cn0"):
            selected[key] = observation
    return tuple((observation, key[1]) for key, observation in sorted(selected.items()))


def uniform_interval(records: Sequence[Record], fallback: float) -> float:
    """Measure regular sampling cadence, rejecting gaps and duplicates."""
    if len(records) < 2:
        return fallback
    epochs = [record_epoch(record) for record in records]
    intervals = [later - earlier for earlier, later in pairwise(epochs)]
    interval = intervals[0]
    if interval <= 0 or any(abs(value - interval) > 1e-4 for value in intervals):
        raise ValueError("time series has gaps, duplicate epochs or irregular sampling")
    return interval


def subscription_plan(
    logs: Sequence[DataLog], *, interval: float, binary: bool
) -> list[tuple[str, Command[CommandResponse]]]:
    """Select supported wire forms and triggers for temporary capture."""
    subscriptions = []
    for log in logs:
        binary_output = binary
        try:
            matcher(log, binary_output)
        except ValueError:
            binary_output = False
        wire_log = log.wire if isinstance(log, AntennaLog) else log
        trigger = Trigger.ON_CHANGED if wire_log.onchanged_only else interval
        output_command = log.output(trigger, binary=binary_output)
        subscriptions.append((log.wire_name(binary=binary_output), output_command))
    return subscriptions


# Log enums inherit from str. Treat a single enum as one log in this overload.
@overload
def capture_live(  # type: ignore[overload-overlap]
    receiver: Receiver,
    logs: DataLog,
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    frames: int | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> tuple[Record, ...]: ...


@overload
def capture_live(
    receiver: Receiver,
    logs: Sequence[DataLog],
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    frames: int | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> dict[str, tuple[Record, ...]]: ...


def capture_live(
    receiver: Receiver,
    logs: DataLog | Sequence[DataLog],
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    frames: int | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> tuple[Record, ...] | dict[str, tuple[Record, ...]]:
    """Capture one log or multiple logs and restore previous subscriptions.

    A log returns a tuple. A sequence returns a dictionary by log name, as do
    progress callbacks and interrupted captures. Records stay in memory.
    ``duration`` limits seconds. ``frames`` can stop a single-log capture early,
    except SATVIS2 epochs may span multiple frames.

    Use ``interval`` in seconds or a documented N4 ``rate_hz``. Event-only logs
    cannot use ``rate_hz``. Actual rates depend on receiver, log, group and firmware.
    """
    interval = logging.output_interval(interval, rate_hz)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval must be finite and positive")
    if frames is not None and (
        isinstance(frames, bool) or not isinstance(frames, int) or frames < 1
    ):
        raise ValueError("frames must be a positive integer")
    selected: Sequence[DataLog] = (
        (logs,) if isinstance(logs, (Log, AntennaLog)) else logs
    )
    if not selected:
        raise ValueError("at least one log is required")
    if any(not isinstance(log, (Log, AntennaLog)) for log in selected):
        raise TypeError("logs must contain Log or AntennaLog values")
    names = [log.value for log in selected]
    if len(set(names)) != len(names):
        raise ValueError("logs must have distinct names")
    if rate_hz is not None and any(
        (log.wire if isinstance(log, AntennaLog) else log).onchanged_only
        for log in selected
    ):
        raise ValueError("ONCHANGED-only logs do not support rate_hz")
    planned = subscription_plan(selected, interval=interval, binary=binary)
    with temporary_subscriptions(receiver, *planned):
        records = receive_records(
            receiver,
            selected,
            duration=duration,
            frames=frames,
            interval=interval,
            arrival_order=arrival_order,
            on_progress=on_progress,
            show_progress=show_progress,
        )
    return records[logs.value] if isinstance(logs, (Log, AntennaLog)) else records


def receive_records(
    receiver: Receiver,
    logs: Sequence[DataLog],
    *,
    duration: float,
    frames: int | None = None,
    interval: float | None = None,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> dict[str, tuple[Record, ...]]:
    """Read logs that are already subscribed, preserving their receiver epochs."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    collected: dict[str, list[Record]] = {log.value: [] for log in logs}
    requests = [(log, _log_matchers(log)) for log in logs]
    deadline = monotonic() + duration
    next_progress = monotonic() + 5
    try:
        while (remaining := deadline - monotonic()) > 0:
            if monotonic() >= next_progress:
                if on_progress is not None:
                    on_progress(
                        {name: tuple(values) for name, values in collected.items()}
                    )
                if show_progress:
                    counts = ", ".join(
                        f"{name}={len(values)}" for name, values in collected.items()
                    )
                    print(
                        f"{counts}; {remaining:.0f}s remaining",
                        file=sys.stderr,
                        flush=True,
                    )
                next_progress = monotonic() + 5
            try:
                message = receiver.receive(timeout=min(remaining, receiver.timeout))
            except ResponseTimeout:
                continue
            for log, matchers in requests:
                records = (
                    (log.decode(message),)
                    if any(request.matches(message) for request in matchers)
                    else ()
                )
                values = collected[log.value]
                values.extend(records)
                if arrival_order is not None:
                    arrival_order.extend(records)
            if (
                frames is not None
                and len(logs) == 1
                and logs[0].value != Log.SATVIS2.value
                and len(collected[logs[0].value]) >= frames
            ):
                break
    except KeyboardInterrupt:
        if show_progress:
            print(
                "Collection interrupted; restoring receiver settings.",
                file=sys.stderr,
                flush=True,
            )
        raise InterruptedCapture(
            {name: tuple(values) for name, values in collected.items()}
        ) from None
    return {name: tuple(values) for name, values in collected.items()}


def iter_frames(
    path: str | os.PathLike[str], *, chunk_size: int = 65536
) -> Iterator[Message]:
    """Decode a transcript incrementally, rejecting damaged or incomplete frames."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    decoder = StreamDecoder(strict=True)
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield from decoder.feed(chunk)
    decoder.finish()


def read_frames(path: str | os.PathLike[str]) -> tuple[Message, ...]:
    """Decode every frame in a captured transcript into memory."""
    return tuple(iter_frames(path))


def replay_receiver(raw: bytes) -> Receiver:
    """Build a receiver that answers from an already captured byte stream."""

    class _Replay(Transport):
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0
            self.closed = False

        def read(self, size: int, timeout: float) -> bytes:
            del timeout
            chunk = self._payload[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

        def write(self, data: bytes, timeout: float) -> None:
            del data, timeout

        def close(self) -> None:
            self.closed = True

    return Receiver(_Replay(raw), timeout=1)


class RecordingSink(Protocol):
    def write(self, data: bytes, /) -> int: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class RecordingTransport:
    def __init__(
        self, transport: Transport, stream: RecordingSink, *, close_stream: bool = True
    ) -> None:
        self.transport, self.stream = transport, stream
        self.close_stream = close_stream

    def read(self, size: int, timeout: float) -> bytes:
        data = self.transport.read(size, timeout)
        try:
            if self.stream.write(data) != len(data):
                raise OSError("short write to capture sink")
            self.stream.flush()
        except OSError as error:
            raise RecordingError(f"capture sink failed: {error}") from error
        return data

    def write(self, data: bytes, timeout: float) -> None:
        self.transport.write(data, timeout)

    def close(self) -> None:
        try:
            self.transport.close()
        finally:
            if self.close_stream:
                self.stream.close()


def load_records(path: str | os.PathLike[str], log: DataLog) -> tuple[Record, ...]:
    """Decode a log from a checksummed wire capture."""
    return decode_records(iter_frames(path), log)
