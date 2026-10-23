"""Counts RTCM receipts and tracks station availability."""

from collections import deque
from dataclasses import dataclass
from time import monotonic

from examples.ntrip_server.station import RTCM_INTERVALS
from um982py.messages import RtcmMessage


@dataclass(frozen=True, slots=True)
class MessageSample:
    received: float
    count: int
    bytes_received: int
    satellites: int | None
    signals: int | None
    current: bool


def count_msm_masks(payload: bytes) -> tuple[int | None, int | None]:
    if len(payload) < 22:
        return None, None
    bits = int.from_bytes(payload, "big")
    satellite_mask = (bits >> (len(payload) * 8 - 137)) & ((1 << 64) - 1)
    signal_mask = (bits >> (len(payload) * 8 - 169)) & ((1 << 32) - 1)
    return satellite_mask.bit_count(), signal_mask.bit_count()


class Telemetry:
    def __init__(self) -> None:
        self.started = monotonic()
        self.messages: dict[int, MessageSample] = {}
        self.received_bytes = 0
        self.sent_bytes = 0
        self.source_failures = 0
        self.rates: deque[tuple[float, int, int]] = deque(maxlen=6)
        self.history: deque[tuple[float, bool]] = deque(maxlen=900)

    def record(self, message: RtcmMessage, now: float) -> None:
        kind = message.message_type
        if kind is None or kind not in dict(RTCM_INTERVALS):
            return
        previous = self.messages.get(kind)
        satellites, signals = (
            count_msm_masks(message.payload) if kind != 1005 else (None, None)
        )
        size = len(message.raw)
        self.received_bytes += size
        self.messages[kind] = MessageSample(
            now,
            (previous.count if previous else 0) + 1,
            (previous.bytes_received if previous else 0) + size,
            satellites,
            signals,
            True,
        )

    def invalidate(self) -> None:
        """Keep lifetime counters while making previous-session gauges unavailable."""
        for kind, sample in tuple(self.messages.items()):
            self.messages[kind] = MessageSample(
                sample.received, sample.count, sample.bytes_received, None, None, False
            )

    def sample(self, now: float, *, ready: bool) -> None:
        if self.history and now - self.history[-1][0] < 1:
            return
        if self.rates and now - self.rates[-1][0] > 3:
            self.rates.clear()
        self.history.append((now, ready))
        self.rates.append((now, self.received_bytes, self.sent_bytes))

    def calculate_bitrates(self, now: float) -> tuple[float, float]:
        if len(self.rates) < 2 or now - self.rates[-1][0] > 3:
            return 0, 0
        first, last = self.rates[0], self.rates[-1]
        elapsed = last[0] - first[0]
        return (
            round((last[1] - first[1]) * 8 / elapsed, 1),
            round((last[2] - first[2]) * 8 / elapsed, 1),
        )

    def build_availability(self, now: float) -> dict[str, object]:
        samples = [sample for sample in self.history if now - sample[0] <= 900]
        buckets: list[bool | None] = [None] * 60
        for received, ready in samples:
            slot = min(59, int((now - received) // 15))
            buckets[59 - slot] = (
                ready if buckets[59 - slot] is None else (buckets[59 - slot] and ready)
            )
        return {
            "window_seconds": 900,
            "sample_count": len(samples),
            "ready_percent": (
                round(100 * sum(ready for _, ready in samples) / len(samples), 2)
                if samples
                else None
            ),
            "buckets": buckets,
            "bucket_seconds": 15,
        }
