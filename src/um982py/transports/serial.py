"""Receiver byte transport over a serial port."""

from time import monotonic

import serial

from um982py.errors import TransportClosed, TransportError


class SerialTransport:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self._closed = False
        try:
            self._port = serial.serial_for_url(
                port, baudrate=baudrate, timeout=0, write_timeout=1, exclusive=True
            )
        except (OSError, ValueError, serial.SerialException) as error:
            raise TransportError(f"Cannot open {port}: {error}") from error

    def read(self, size: int, timeout: float) -> bytes:
        self._check_open()
        if size < 0:
            raise ValueError("read size must be non-negative")
        if size == 0:
            return b""
        try:
            self._port.timeout = max(0, timeout)
            first = self._port.read(1)
            if not first:
                return b""
            waiting = min(self._port.in_waiting, max(0, size - 1))
            return first + self._port.read(waiting)
        except (OSError, serial.SerialException) as error:
            raise TransportError("Serial read failed") from error

    def write(self, data: bytes, timeout: float) -> None:
        self._check_open()
        deadline = monotonic() + timeout
        sent = 0
        try:
            while sent < len(data):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TransportError("Serial write timed out")
                self._port.write_timeout = remaining
                count = self._port.write(data[sent:])
                if not count:
                    raise TransportError("Serial write made no progress")
                sent += count
        except (OSError, serial.SerialException) as error:
            raise TransportError("Serial write failed") from error

    def close(self) -> None:
        if not self._closed:
            self._port.close()
            self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise TransportClosed("Serial transport is closed")
