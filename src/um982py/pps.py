"""Read Linux PPS edge timestamps and compare explicitly associated UTC times."""

import ctypes
import math
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import TracebackType
from typing import Literal, Self


class _KernelTime(ctypes.Structure):
    _fields_ = [
        ("sec", ctypes.c_int64),
        ("nsec", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


class _KernelInfo(ctypes.Structure):
    _fields_ = [
        ("assert_sequence", ctypes.c_uint32),
        ("clear_sequence", ctypes.c_uint32),
        ("assert_time", _KernelTime),
        ("clear_time", _KernelTime),
        ("current_mode", ctypes.c_int),
    ]


class _KernelFetch(ctypes.Structure):
    _fields_ = [("info", _KernelInfo), ("timeout", _KernelTime)]


# Linux defines PPS_FETCH with the size of a pointer, not the structure size.
_PPS_FETCH = (3 << 30) | (ctypes.sizeof(ctypes.c_void_p) << 16) | (ord("p") << 8) | 0xA4
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PpsEdge:
    """A kernel edge sequence and timestamp in host CLOCK_REALTIME."""

    edge: Literal["assert", "clear"]
    sequence: int
    seconds: int
    nanoseconds: int

    def __post_init__(self) -> None:
        if self.edge not in ("assert", "clear") or not 0 <= self.sequence < 2**32:
            raise ValueError("invalid PPS edge or sequence")
        if not 0 <= self.nanoseconds < 1_000_000_000:
            raise ValueError("PPS nanoseconds must be in 0..999999999")

    @property
    def realtime_ns(self) -> int:
        return self.seconds * 1_000_000_000 + self.nanoseconds


@dataclass(frozen=True, slots=True)
class PpsSnapshot:
    """The most recent assert and clear edges returned by the kernel."""

    assert_edge: PpsEdge | None
    clear_edge: PpsEdge | None
    mode: int


def missed_pps_edges(previous: PpsEdge, current: PpsEdge) -> int:
    """Count gaps assuming the same device instance and fewer than 2**31 edges.

    A reset near sequence wrap cannot be distinguished from a wrap.
    """
    if previous.edge != current.edge:
        raise ValueError("PPS edges must have the same polarity")
    difference = (current.sequence - previous.sequence) % 2**32
    if difference == 0 or difference >= 2**31:
        raise ValueError("PPS sequence did not advance or was reset")
    return difference - 1


def pps_clock_offset_ns(edge: PpsEdge, receiver_utc: datetime) -> int:
    """Compare host time with UTC explicitly associated with this same pulse.

    The caller must establish the pulse-to-receiver-time association and any
    configured pulse delay. The result is host CLOCK_REALTIME minus UTC.
    """
    if receiver_utc.utcoffset() is None:
        raise ValueError("receiver UTC time must be timezone-aware")
    delta = receiver_utc.astimezone(UTC) - _UNIX_EPOCH
    reference_ns = (
        (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    ) * 1000
    return edge.realtime_ns - reference_ns


class PpsDevice:
    """Read an already configured Linux PPS device on x86-64 or AArch64.

    No receiver, kernel PPS configuration or system clock is changed. Kernel
    timestamps use host CLOCK_REALTIME, not receiver UTC; sequence numbers
    identify missed or repeated edge samples. Fetching is not thread-safe with
    concurrent fetch or close operations.
    """

    def __init__(self, path: Path) -> None:
        if (
            sys.platform != "linux"
            or platform.machine().lower() not in ("x86_64", "aarch64")
            or ctypes.sizeof(ctypes.c_void_p) != 8
        ):
            raise NotImplementedError(
                "Linux PPS requires 64-bit Python on x86-64 or AArch64"
            )
        self._fd: int | None = os.open(path, os.O_RDONLY | os.O_CLOEXEC)

    def fetch(self, *, timeout: float = 2.0) -> PpsSnapshot:
        """Wait for a PPS event and return the kernel's latest edge snapshots."""
        if self._fd is None:
            raise ValueError("PPS device is closed")
        if not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise ValueError("timeout must be finite and in (0, 86400] seconds")
        timeout_ns = max(1, round(timeout * 1_000_000_000))
        seconds, nanoseconds = divmod(timeout_ns, 1_000_000_000)
        request = _KernelFetch()
        request.timeout.sec = seconds
        request.timeout.nsec = nanoseconds
        buffer = bytearray(bytes(request))
        import_module("fcntl").ioctl(self._fd, _PPS_FETCH, buffer, True)
        result = _KernelFetch.from_buffer_copy(buffer)

        def edge(
            kind: Literal["assert", "clear"], sequence: int, stamp: _KernelTime
        ) -> PpsEdge | None:
            if sequence == 0 and stamp.sec == 0 and stamp.nsec == 0:
                return None
            return PpsEdge(kind, sequence, stamp.sec, stamp.nsec)

        return PpsSnapshot(
            edge("assert", result.info.assert_sequence, result.info.assert_time),
            edge("clear", result.info.clear_sequence, result.info.clear_time),
            result.info.current_mode,
        )

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> Self:
        if self._fd is None:
            raise ValueError("PPS device is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
