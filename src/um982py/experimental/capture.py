"""Bounded transport captures and receiver state snapshots."""

from collections import Counter
from dataclasses import dataclass
from math import isfinite
from time import monotonic

from um982py._receiver_state import ascii_fields, ordered_log_list, receiver_state
from um982py.messages import (
    BinaryMessage,
    CommandResponse,
    Message,
)
from um982py.protocol import StreamDecoder
from um982py.transports.base import Transport

__all__ = [
    "CaptureAnalysis",
    "RecordingTransport",
    "analyze_capture",
    "ascii_fields",
    "capture_wire",
    "ordered_log_list",
    "receiver_state",
]


class RecordingTransport:
    """Wraps a transport and records every byte read."""

    def __init__(self, transport: Transport, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.transport = transport
        self.limit = limit
        self.raw = bytearray()
        self.recording = True

    def read(self, size: int, timeout: float) -> bytes:
        chunk = self.transport.read(size, timeout)
        if self.recording:
            self.raw.extend(chunk[: max(0, self.limit - len(self.raw))])
        return chunk

    def write(self, data: bytes, timeout: float) -> None:
        self.transport.write(data, timeout)

    def close(self) -> None:
        self.transport.close()

    @property
    def limit_reached(self) -> bool:
        """Return true once ``limit`` bytes have been recorded."""
        return len(self.raw) >= self.limit


@dataclass(frozen=True, slots=True)
class CaptureAnalysis:
    """Classification of a raw capture, with its bytes unchanged."""

    messages: tuple[Message, ...]
    binary_ids: tuple[tuple[int, int], ...]
    binary_payload_bytes: int
    replies: tuple[CommandResponse, ...]
    decoder_errors: tuple[str, ...]
    discarded_bytes: int
    pending_bytes: int


def capture_wire(
    transport: Transport, seconds: float, *, max_bytes: int = 8 * 1024 * 1024
) -> bytes:
    """Read exact transport bytes until the time or byte limit."""
    if isinstance(seconds, bool) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be finite and positive")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    deadline = monotonic() + seconds
    wire = bytearray()
    while len(wire) < max_bytes:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        chunk = transport.read(min(65536, max_bytes - len(wire)), min(0.1, remaining))
        wire.extend(chunk)
    return bytes(wire)


def analyze_capture(raw: bytes) -> CaptureAnalysis:
    """Classify known frames without changing the capture bytes."""
    decoder = StreamDecoder()
    messages = decoder.feed(raw)
    binaries = tuple(m for m in messages if isinstance(m, BinaryMessage))
    return CaptureAnalysis(
        messages,
        tuple(sorted(Counter(m.header.message_id for m in binaries).items())),
        sum(len(m.payload) for m in binaries),
        tuple(m for m in messages if isinstance(m, CommandResponse)),
        tuple(str(error) for error in decoder.errors),
        decoder.discarded_bytes,
        len(decoder.pending),
    )
