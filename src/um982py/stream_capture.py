"""Incremental live and replay capture with bounded application memory."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from math import isfinite
from time import monotonic

from um982py.antenna import AntennaLog
from um982py.capture import DataLog, _matching_requests, subscription_plan
from um982py.commands import logging
from um982py.errors import ResponseTimeout
from um982py.messages import Message, Record
from um982py.receiver import Receiver
from um982py.subscriptions import temporary_subscriptions


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
        if not isfinite(expected_interval_s) or expected_interval_s <= 0:
            raise ValueError("expected interval must be finite and positive")
        if not isfinite(tolerance_s) or not 0 <= tolerance_s < expected_interval_s:
            raise ValueError("tolerance must be non-negative and less than interval")
        self.expected_interval_s = expected_interval_s
        self.tolerance_s = tolerance_s
        self.previous: float | None = None

    def observe(self, epoch: float) -> EpochEvent | None:
        if not isfinite(epoch):
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


def iter_decoded_records(
    messages: Iterable[Message], logs: Sequence[DataLog]
) -> Iterator[tuple[str, Record]]:
    """Yield matching records in arrival order as input arrives."""
    requests = [(log, _matching_requests(log)) for log in logs]
    for message in messages:
        for log, matchers in requests:
            if any(request.matches(message) for request in matchers):
                yield log.value, log.decode(message)


def iter_live_records(
    receiver: Receiver,
    logs: Sequence[DataLog],
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    binary: bool = True,
) -> Iterator[tuple[str, Record]]:
    """Temporarily subscribe and yield records until the duration elapses.

    Close the iterator if you stop early, so the receiver's subscriptions can
    be restored. Processing happens in the reader thread, so a slow consumer
    can cause data loss at the transport. Use RecordingTransport separately if
    you need to preserve the raw bytes.
    """
    interval = logging.output_interval(interval, rate_hz)
    if not isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not isfinite(interval) or interval <= 0:
        raise ValueError("interval must be finite and positive")
    if rate_hz is not None and any(
        (log.wire if isinstance(log, AntennaLog) else log).onchanged_only
        for log in logs
    ):
        raise ValueError("ONCHANGED-only logs do not support rate_hz")
    planned = subscription_plan(logs, interval=interval, binary=binary)
    with temporary_subscriptions(receiver, *planned):
        deadline = monotonic() + duration

        def messages() -> Iterator[Message]:
            while (remaining := deadline - monotonic()) > 0:
                try:
                    message = receiver.receive(timeout=min(remaining, receiver.timeout))
                except ResponseTimeout:
                    continue
                yield message

        yield from iter_decoded_records(messages(), logs)
