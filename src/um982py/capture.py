"""Capture bounded live logs and replay wire transcripts."""

import math
import os
import sys
from bisect import bisect_left
from collections.abc import (
    Callable,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import suppress
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from time import monotonic
from typing import Protocol

from um982py.antenna import AntennaLog
from um982py.commands import Log, Trigger, logging
from um982py.commands.core import Command
from um982py.errors import RecordingError, ResponseTimeout
from um982py.geodesy import receiver_ecef
from um982py.gnss import F_L1, F_L2, F_L5
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
    "EpochEvent",
    "EpochTracker",
    "InterruptedCapture",
    "RecordingTransport",
    "capture_live",
    "decode_records",
    "gps_signals",
    "iter_decoded_records",
    "iter_frames",
    "iter_live_records",
    "latest_epoch",
    "load_records",
    "matcher",
    "read_frames",
    "receive_records",
    "replay_receiver",
    "select_position",
    "uniform_interval",
]

GPS_FREQUENCIES = {0: F_L1, 9: F_L2, 17: F_L2, 14: F_L5}

type DataLog = Log | AntennaLog


class InterruptedCapture(KeyboardInterrupt):
    """A cancelled capture whose ``records`` map log names to collected
    records."""

    def __init__(self, records: dict[str, tuple[Record, ...]]) -> None:
        super().__init__()
        self.records = records


def select_position(
    records: Iterable[Record], epoch: float, tolerance: float
) -> Record:
    """``epoch`` is absolute GPS seconds, and ``tolerance`` is seconds. Invalid,
    untimestamped and near-geocentre positions are ignored. Equal-distance
    matches prefer the earlier epoch, independently of capture arrival order.
    Coordinates describe a terrestrial GNSS receiver, not a satellite orbit.
    """
    if not math.isfinite(epoch):
        raise ValueError("position epoch must be finite")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("position tolerance must be finite and non-negative")
    eligible = [
        (abs(time - epoch), time, record)
        for time, record in _valid_positions(records)
        if abs(time - epoch) <= tolerance
    ]
    if not eligible:
        raise ValueError("no valid receiver position within the epoch tolerance")
    return min(eligible, key=lambda item: (item[0], item[1]))[2]


def _valid_positions(records: Iterable[Record]) -> Iterator[tuple[float, Record]]:
    for record in records:
        if record.get("p_sol_status") not in (0, "SOL_COMPUTED"):
            continue
        try:
            xyz = receiver_ecef(record)
            time = gps_epoch(record)
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(x) for x in xyz) and math.dist(xyz, (0, 0, 0)) > 1e6:
            yield time, record


def select_position_pair(
    observations: Iterable[Record], positions: Iterable[Record], tolerance: float
) -> tuple[Record, Record]:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("position tolerance must be finite and non-negative")
    by_epoch: dict[float, Record] = {}
    for epoch, position in _valid_positions(positions):
        by_epoch.setdefault(epoch, position)
    epochs = sorted(by_epoch)
    if epochs:
        for observation in observations:
            epoch = gps_epoch(observation)
            index = bisect_left(epochs, epoch)
            nearby = epochs[max(0, index - 1) : index + 1]
            nearest = min(nearby, key=lambda value: (abs(value - epoch), value))
            if abs(nearest - epoch) <= tolerance:
                return observation, by_epoch[nearest]
    raise ValueError("no valid receiver position within the epoch tolerance")


def latest_epoch(records: Sequence[Record]) -> tuple[Record, ...]:
    """Return the constellation frames from the newest epoch only."""
    if not records:
        return ()
    newest = max(gps_epoch(record) for record in records)
    by_system: dict[str, Record] = {}
    for record in records:
        if abs(gps_epoch(record) - newest) < 1e-5:
            by_system[str(record.get("constellation", record.name))] = record
    return tuple(by_system.values())


def matcher(log: DataLog, binary: bool) -> Command[Message]:
    """Match a data log, including logs emitted only on events."""
    wire = log.wire
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
    return tuple(record for _, record in iter_decoded_records(frames, (log,)))


def iter_decoded_records(
    messages: Iterable[Message],
    logs: Sequence[DataLog],
    *,
    max_records_per_log: int | None = None,
) -> Iterator[tuple[str, Record]]:
    """Yield matching records in arrival order as input arrives.

    An optional limit applies separately to each logical log. Frames beyond a
    log's limit are not decoded, while other selected logs keep streaming.
    """
    if max_records_per_log is not None and (
        type(max_records_per_log) is not int or max_records_per_log < 1
    ):
        raise ValueError("max_records_per_log must be a positive integer")
    counts = {log.value: 0 for log in logs}
    requests = [(log, _log_matchers(log)) for log in logs]
    for message in messages:
        for log, matchers in requests:
            if (
                max_records_per_log is not None
                and counts[log.value] >= max_records_per_log
            ):
                continue
            if any(request.matches(message) for request in matchers):
                counts[log.value] += 1
                yield log.value, log.decode(message)


def gps_signals(
    record: Record,
    frequencies: Sequence[float] = (F_L1, F_L5),
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
    epochs = [gps_epoch(record) for record in records]
    intervals = [later - earlier for earlier, later in pairwise(epochs)]
    interval = intervals[0]
    if interval <= 0 or any(abs(value - interval) > 1e-4 for value in intervals):
        raise ValueError("time series has gaps, duplicate epochs or irregular sampling")
    return interval


def subscription_plan(
    logs: Sequence[DataLog],
    *,
    interval: float,
    binary: bool,
    intervals: Mapping[DataLog, float] | None = None,
) -> list[tuple[str, Command[CommandResponse]]]:
    """Select supported wire forms and triggers for temporary capture."""
    overrides = {} if intervals is None else dict(intervals)
    for log, value in overrides.items():
        if not isinstance(log, (Log, AntennaLog)) or log not in logs:
            raise ValueError("intervals must refer to selected logs")
        wire_log = log.wire
        if wire_log.onchanged_only:
            raise ValueError("ONCHANGED-only logs do not support intervals")
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError("intervals must be finite and positive")
    subscriptions = []
    for log in logs:
        binary_output = binary
        try:
            matcher(log, binary_output)
        except ValueError:
            binary_output = False
        wire_log = log.wire
        trigger = (
            Trigger.ON_CHANGED
            if wire_log.onchanged_only
            else overrides.get(log, interval)
        )
        output_command = log.output(trigger, binary=binary_output)
        subscriptions.append((log.wire_name(binary=binary_output), output_command))
    return subscriptions


def capture_live(
    receiver: Receiver,
    logs: DataLog | Sequence[DataLog],
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    intervals: Mapping[DataLog, float] | None = None,
    frames: int | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
    show_progress: bool = False,
) -> dict[str, tuple[Record, ...]]:
    """Capture logs and restore previous subscriptions.

    Results, progress callbacks and interrupted captures map log names to
    tuples of records. Records stay in memory.
    ``duration`` limits seconds. ``frames`` can stop a single-log capture early,
    except SATVIS2 epochs may span multiple frames.

    Use ``interval`` in seconds or a documented N4 ``rate_hz``. Event-only logs
    cannot use ``rate_hz``. ``intervals`` overrides the default period in seconds
    for selected periodic logs. Actual rates depend on receiver, log, group and
    firmware.
    Capture preserves received epochs, including repeats and gaps, and does
    not resample. Subscription restoration can fail after a disconnect. For longer
    recordings use ``SessionRecorder`` or stream with ``iter_live_records``.
    """
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
    interval = _capture_interval(
        selected, duration=duration, interval=interval, rate_hz=rate_hz
    )
    planned = subscription_plan(
        selected, interval=interval, binary=binary, intervals=intervals
    )
    with temporary_subscriptions(receiver, *planned):
        return receive_records(
            receiver,
            selected,
            duration=duration,
            frames=frames,
            interval=interval,
            arrival_order=arrival_order,
            on_progress=on_progress,
            show_progress=show_progress,
        )


def _capture_interval(
    logs: Sequence[DataLog],
    *,
    duration: float,
    interval: float | None,
    rate_hz: float | None,
) -> float:
    """Validate a temporary capture and resolve its output interval."""
    resolved = logging.output_interval(interval, rate_hz)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not math.isfinite(resolved) or resolved <= 0:
        raise ValueError("interval must be finite and positive")
    if rate_hz is not None and any(log.wire.onchanged_only for log in logs):
        raise ValueError("ONCHANGED-only logs do not support rate_hz")
    return resolved


def _received(
    receiver: Receiver,
    duration: float,
    tick: Callable[[float], None] | None = None,
) -> Iterator[Message]:
    """Yield frames until ``duration`` elapses, calling ``tick`` with time left."""
    deadline = monotonic() + duration
    while (remaining := deadline - monotonic()) > 0:
        if tick is not None:
            tick(remaining)
        try:
            yield receiver.receive(timeout=min(remaining, receiver.timeout))
        except ResponseTimeout:
            continue


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
    next_progress = monotonic() + 5

    def snapshot() -> dict[str, tuple[Record, ...]]:
        return {name: tuple(values) for name, values in collected.items()}

    def progress(remaining: float) -> None:
        nonlocal next_progress
        if monotonic() < next_progress:
            return
        if on_progress is not None:
            on_progress(snapshot())
        if show_progress:
            counts = ", ".join(
                f"{name}={len(values)}" for name, values in collected.items()
            )
            print(f"{counts}; {remaining:.0f}s remaining", file=sys.stderr, flush=True)
        next_progress = monotonic() + 5

    limited = (
        frames is not None and len(logs) == 1 and logs[0].value != Log.SATVIS2.value
    )
    try:
        for name, record in iter_decoded_records(
            _received(receiver, duration, progress), logs
        ):
            collected[name].append(record)
            if arrival_order is not None:
                arrival_order.append(record)
            if limited and frames is not None and len(collected[name]) >= frames:
                break
    except KeyboardInterrupt:
        if show_progress:
            print(
                "Collection interrupted; restoring receiver settings.",
                file=sys.stderr,
                flush=True,
            )
        raise InterruptedCapture(snapshot()) from None
    return snapshot()


def iter_live_records(
    receiver: Receiver,
    logs: Sequence[DataLog],
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    intervals: Mapping[DataLog, float] | None = None,
    binary: bool = True,
) -> Generator[tuple[str, Record], None, None]:
    """Temporarily subscribe and yield records until the duration elapses.

    ``intervals`` overrides the default period in seconds for selected periodic
    logs, allowing slow status logs alongside fast observations.

    If you stop early, close the iterator so the receiver's subscriptions can be
    restored. Processing happens in the reader thread, so a slow consumer can
    cause data loss at the transport. Use RecordingTransport separately if you
    need to preserve the raw bytes.
    """
    resolved = _capture_interval(
        logs, duration=duration, interval=interval, rate_hz=rate_hz
    )
    planned = subscription_plan(
        logs, interval=resolved, binary=binary, intervals=intervals
    )
    with temporary_subscriptions(receiver, *planned):
        yield from iter_decoded_records(_received(receiver, duration), logs)


@dataclass(frozen=True, slots=True)
class EpochEvent:
    previous: float
    current: float
    kind: str


class EpochTracker:
    """Detect gaps and non-increasing epochs for one explicitly chosen series."""

    def __init__(
        self, *, expected_interval_s: float, tolerance_s: float = 0.0001
    ) -> None:
        if not math.isfinite(expected_interval_s) or expected_interval_s <= 0:
            raise ValueError("expected interval must be finite and positive")
        if not math.isfinite(tolerance_s) or not 0 <= tolerance_s < expected_interval_s:
            raise ValueError("tolerance must be non-negative and less than interval")
        self.expected_interval_s = expected_interval_s
        self.tolerance_s = tolerance_s
        self.previous: float | None = None

    def observe(self, epoch: float) -> EpochEvent | None:
        if not math.isfinite(epoch):
            raise ValueError("epoch must be finite")
        previous, self.previous = self.previous, epoch
        if previous is None:
            return None
        delta = epoch - previous
        if delta <= 0:
            return EpochEvent(previous, epoch, "non_increasing")
        if delta > self.expected_interval_s + self.tolerance_s:
            return EpochEvent(previous, epoch, "gap")
        return None


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
