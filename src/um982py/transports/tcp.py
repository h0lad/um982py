"""Receiver byte transport over TCP."""

import socket

from um982py.errors import TransportClosed, TransportError


class TcpTransport:
    def __init__(self, host: str, port: int, *, timeout: float = 3) -> None:
        self._closed = False
        try:
            self._socket = socket.create_connection((host, port), timeout)
        except OSError as error:
            raise TransportError(f"Cannot connect to {host}:{port}: {error}") from error

    def read(self, size: int, timeout: float) -> bytes:
        self._check_open()
        if size < 0:
            raise ValueError("read size must be non-negative")
        if size == 0:
            return b""
        self._socket.settimeout(timeout)
        try:
            chunk = self._socket.recv(size)
        except TimeoutError:
            return b""
        except OSError as error:
            raise TransportError("TCP read failed") from error
        if not chunk:
            raise TransportClosed("TCP peer disconnected")
        return chunk

    def write(self, data: bytes, timeout: float) -> None:
        self._check_open()
        self._socket.settimeout(timeout)
        try:
            self._socket.sendall(data)
        except OSError as error:
            raise TransportError("TCP write failed") from error

    def close(self) -> None:
        if not self._closed:
            self._socket.close()
            self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise TransportClosed("TCP transport is closed")
