"""Capture bounded live logs and replay wire transcripts."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from itertools import pairwise
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, BinaryIO

from um982py._firmware_logs import FirmwareLog
from um982py.antenna import AntennaLog
from um982py.augmentation import enable_augmentation
from um982py.commands import Log, Trigger, logging
from um982py.commands.core import Command
from um982py.errors import ResponseTimeout
from um982py.measurement import gps_epoch
from um982py.messages import Message, Record
from um982py.protocol import StreamDecoder
from um982py.receiver import Receiver
from um982py.subscriptions import temporary_subscriptions
from um982py.transports.base import Transport

if TYPE_CHECKING:
    import argparse

__all__ = [
    "GPS_FREQUENCIES",
    "AntennaLog",
    "DataLog",
    "InterruptedCapture",
    "RecordingTransport",
    "capture_live",
    "capture_logs",
    "capture_records",
    "decode_records",
    "epoch_seconds",
    "gps_signals",
    "iter_frames",
    "latest_epoch",
    "load_records",
    "matcher",
    "open_receiver",
    "read_frames",
    "receive_records",
    "record_epoch",
    "replay_receiver",
    "uniform_interval",
]

GPS_FREQUENCIES = {0: 1575.42e6, 9: 1227.60e6, 17: 1227.60e6, 14: 1176.45e6}

type DataLog = Log | FirmwareLog | AntennaLog


class InterruptedCapture(KeyboardInterrupt):
    """A cancelled read with the data received before cancellation."""

    def __init__(self, records: dict[str, tuple[Record, ...]]) -> None:
        super().__init__()
        self.records = records


def epoch_seconds(message: Message) -> float:
    """Absolute GPS seconds from either supported data-frame header."""
    return gps_epoch(message)


def record_epoch(record: Record) -> float:
    """Return the receiver epoch of a decoded record, requiring a timestamp."""
    if record.message is None:
        raise ValueError(f"{record.name} record carries no receiver timestamp")
    return epoch_seconds(record.message)


def latest_epoch(records: Sequence[Record]) -> tuple[Record, ...]:
    """All constellation frames at the newest epoch, without mixing skies."""
    if not records:
        return ()
    newest = max(record_epoch(record) for record in records)
    by_system: dict[str, Record] = {}
    for record in records:
        if abs(record_epoch(record) - newest) < 1e-5:
            by_system[str(record.get("constellation", record.name))] = record
    return tuple(by_system.values())


def matcher(log: DataLog, binary: bool) -> Command[Message]:
    """Match a data log, including event-only logs that cannot be queried."""
    if isinstance(log, (Log, AntennaLog)):
        if isinstance(log, AntennaLog):
            return log.request(binary=binary)
        return logging.request(
            log.wire_name(binary=binary), message_id=log.definition.message_id
        )
    return log.request(binary=binary)


def decode_records(frames: Iterable[Message], log: DataLog) -> tuple[Record, ...]:
    """Decode every matching ASCII or binary frame, retaining malformed-body errors."""
    requests = [matcher(log, False)]
    with suppress(ValueError):
        requests.append(matcher(log, True))
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
    times = [record_epoch(record) for record in records]
    intervals = [b - a for a, b in pairwise(times)]
    interval = intervals[0]
    if interval <= 0 or any(abs(value - interval) > 1e-4 for value in intervals):
        raise ValueError("time series has gaps, duplicate epochs or irregular sampling")
    return interval


def capture_records(
    args: argparse.Namespace,
    logs: Sequence[DataLog],
    *,
    frames: int | None = None,
    interval: float = 1.0,
    duration: float | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
) -> dict[str, tuple[Record, ...]]:
    """Collect logs using the command-line capture options."""
    from um982py.console_capture import capture_records as cli_capture_records

    return cli_capture_records(
        args,
        logs,
        frames=frames,
        interval=interval,
        duration=duration,
        binary=binary,
        arrival_order=arrival_order,
        on_progress=on_progress,
        open_receiver_fn=open_receiver,
    )


def capture_live(
    receiver: Receiver,
    logs: Sequence[DataLog],
    *,
    duration: float,
    interval: float = 1.0,
    frames: int | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> dict[str, tuple[Record, ...]]:
    """Collect logs on an open receiver and restore its subscriptions afterward."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval must be finite and positive")
    if frames is not None and frames < 1:
        raise ValueError("frames must be positive")
    planned = []
    for log in logs:
        form = binary
        try:
            matcher(log, form)
        except ValueError:
            form = False
        try:
            start = log.output(interval, binary=form)
        except ValueError:
            start = log.output(Trigger.ON_CHANGED, binary=form)
        planned.append((log.wire_name(binary=form), start))
    with temporary_subscriptions(receiver, *planned):
        return receive_records(
            receiver,
            logs,
            duration=duration,
            frames=frames,
            interval=interval,
            arrival_order=arrival_order,
            on_progress=on_progress,
            show_progress=show_progress,
        )


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
    """Read already subscribed logs together while preserving their actual epochs."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    collected: dict[str, list[Record]] = {log.value: [] for log in logs}
    trimmed: set[str] = set()
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
            for log in logs:
                records = decode_records((message,), log)
                values = collected[log.value]
                values.extend(records)
                if arrival_order is not None:
                    arrival_order.extend(records)
                if (
                    interval is not None
                    and interval < 1.0
                    and log.value not in trimmed
                    and len(values) == 2
                ):
                    trimmed.add(log.value)
                    with suppress(ValueError):
                        if (
                            record_epoch(values[1]) - record_epoch(values[0])
                            > interval + 1e-4
                        ):
                            dropped = values.pop(0)
                            if arrival_order is not None and dropped in arrival_order:
                                arrival_order.remove(dropped)
            if (
                frames is not None
                and len(logs) == 1
                and logs[0] != FirmwareLog.SATVIS2
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


def iter_frames(path: Path, *, chunk_size: int = 65536) -> Iterator[Message]:
    """Decode a transcript incrementally, rejecting damaged or incomplete frames."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    decoder = StreamDecoder(strict=True)
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield from decoder.feed(chunk)
    decoder.finish()


def read_frames(path: Path) -> tuple[Message, ...]:
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


def open_receiver(args: argparse.Namespace) -> Receiver:
    """Open a receiver using the command-line connection options."""
    from um982py.console_capture import open_receiver as cli_open_receiver

    return cli_open_receiver(args, augmentation=enable_augmentation)


class RecordingTransport:
    def __init__(self, transport: Transport, stream: BinaryIO) -> None:
        self.transport, self.stream = transport, stream

    def read(self, size: int, timeout: float) -> bytes:
        data = self.transport.read(size, timeout)
        self.stream.write(data)
        self.stream.flush()
        return data

    def write(self, data: bytes, timeout: float) -> None:
        self.transport.write(data, timeout)

    def close(self) -> None:
        try:
            self.transport.close()
        finally:
            self.stream.close()


def capture_logs(
    args: argparse.Namespace,
    logs: Sequence[DataLog],
    *,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
) -> dict[str, tuple[Record, ...]]:
    """Capture or replay all requested logs together."""
    return capture_records(
        args,
        logs,
        duration=args.duration,
        interval=args.interval,
        arrival_order=arrival_order,
        on_progress=on_progress,
    )


def load_records(path: Path, log: DataLog) -> tuple[Record, ...]:
    """Decode a log from a checksummed wire capture."""
    return decode_records(read_frames(path), log)
