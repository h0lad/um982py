"""Read RTCM correction streams from NTRIP v1 and v2 casters."""

from __future__ import annotations

import base64
import math
import re
import socket
import ssl
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Literal, Self
from urllib.parse import urlsplit

from um982py.errors import ProtocolError
from um982py.geodesy import haversine_distance
from um982py.messages.navigation import Fix
from um982py.protocol.ascii import parse_ascii

if TYPE_CHECKING:
    from types import TracebackType


class NtripError(ProtocolError):
    """The caster rejected the request or sent an invalid response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NtripDisconnected(NtripError):
    """The caster disconnected before completing its response or chunk."""


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Bounded exponential delays for recoverable NTRIP failures."""

    initial_seconds: float = 1.0
    maximum_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 0 < self.initial_seconds <= self.maximum_seconds < float("inf"):
            raise ValueError("reconnect delays must be finite, positive and ordered")

    def next_delay(self, current: float) -> float:
        """Return the next delay, capped at the configured maximum."""
        if not 0 < current < float("inf"):
            raise ValueError("current delay must be finite and positive")
        return min(current * 2, self.maximum_seconds)


def retryable_ntrip_error(error: BaseException) -> bool:
    """Recognize retryable transport and caster errors.

    TLS and authentication failures stop the retry loop.
    """
    if isinstance(error, ssl.SSLError):
        return False
    if isinstance(error, NtripDisconnected):
        return True
    if isinstance(error, NtripError):
        return error.status_code in (408, 429) or (
            error.status_code is not None and 500 <= error.status_code < 600
        )
    return isinstance(error, OSError)


class NtripClient:
    def __init__(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        initial_gga: bytes | None = None,
        timeout: float = 10.0,
        version: Literal[1, 2] = 2,
        _sourcetable: bool = False,
    ) -> None:
        address = urlsplit(url)
        if (
            address.scheme not in ("http", "https")
            or not address.hostname
            or (not _sourcetable and not address.path.strip("/"))
            or (_sourcetable and address.path not in ("", "/"))
            or address.username is not None
            or address.password is not None
            or address.query
            or address.fragment
            or any(char in address.path for char in "\r\n ")
        ):
            raise ValueError("Invalid NTRIP caster or mountpoint URL")
        if (username is None) != (password is None):
            raise ValueError("NTRIP username and password must be supplied together")
        if username is not None and any(
            char in username + (password or "") for char in "\r\n"
        ):
            raise ValueError("NTRIP credentials must not contain line breaks")
        if initial_gga is not None:
            self._validate_gga(initial_gga)
        if not 0 < timeout < float("inf"):
            raise ValueError("NTRIP timeout must be finite and positive")
        if version not in (1, 2):
            raise ValueError("NTRIP version must be 1 or 2")
        try:
            port = address.port
        except ValueError as error:
            raise ValueError("Invalid NTRIP port") from error
        if port == 0:
            raise ValueError("Invalid NTRIP port")
        if port is None:
            port = 443 if address.scheme == "https" else 2101
        self.url = url
        self.host = address.hostname
        self.port = port
        self.mountpoint = address.path or "/"
        self._sourcetable = _sourcetable
        self.secure = address.scheme == "https"
        self.username = username
        self.password = password
        self.initial_gga = initial_gga
        self.timeout = timeout
        self.version = version
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._buffer = bytearray()
        self._chunked = False
        self._remaining = 0
        self._need_chunk_terminator = False
        self._ended = False

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        self.close()
        connection = socket.create_connection((self.host, self.port), self.timeout)
        self._socket = connection
        try:
            if self.secure:
                connection = ssl.create_default_context().wrap_socket(
                    connection, server_hostname=self.host
                )
            self._socket = connection
            connection.settimeout(self.timeout)
            host = f"[{self.host}]" if ":" in self.host else self.host
            if self.port != (443 if self.secure else 80):
                host = f"{host}:{self.port}"
            headers = [
                f"GET {self.mountpoint} HTTP/1.{1 if self.version == 2 else 0}",
                f"Host: {host}",
            ]
            if self.version == 2:
                headers.append("Ntrip-Version: Ntrip/2.0")
            headers.extend(
                (
                    "User-Agent: NTRIP um982py/1.0",
                    "Accept: */*",
                    "Connection: close",
                )
            )
            if self.username is not None:
                token = base64.b64encode(
                    f"{self.username}:{self.password}".encode()
                ).decode("ascii")
                headers.append(f"Authorization: Basic {token}")
            if self.initial_gga is not None and self.version == 2:
                headers.append(f"Ntrip-GGA: {self.initial_gga[:-2].decode('ascii')}")
            connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
            self._read_response()
            if self.initial_gga is not None and self.version == 1:
                self.send_gga(self.initial_gga)
        except BaseException:
            self.close()
            raise

    def _line(self) -> bytes:
        if self._socket is None:
            raise NtripError("NTRIP client is not connected")
        while True:
            end = self._buffer.find(b"\n")
            if end >= 0:
                if end > 8192:
                    raise NtripError("NTRIP line exceeds 8 KiB")
                line = bytes(self._buffer[: end + 1])
                del self._buffer[: end + 1]
                return line.rstrip(b"\r\n")
            if len(self._buffer) > 8192:
                raise NtripError("NTRIP line exceeds 8 KiB")
            if not self._read_socket():
                raise NtripDisconnected("Incomplete NTRIP response")

    def _read_socket(self) -> bytes:
        if self._socket is None:
            raise NtripError("NTRIP client is not connected")
        data = self._socket.recv(4096)
        self._buffer.extend(data)
        return data

    def _take(self, size: int) -> bytes:
        while len(self._buffer) < size:
            if not self._read_socket():
                raise NtripDisconnected("NTRIP chunk ended early")
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _read_response(self) -> None:
        status = self._line()
        parts = status.split(b" ", 2)
        valid_status = status.startswith((b"ICY ", b"HTTP/1.")) or (
            self._sourcetable and status.startswith(b"SOURCETABLE ")
        )
        if len(parts) < 2 or not valid_status:
            raise NtripError("Invalid NTRIP status line")
        if parts[1] != b"200":
            reason = parts[2].decode("ascii", "replace") if len(parts) > 2 else ""
            code = parts[1].decode("ascii", "replace")
            raise NtripError(
                f"NTRIP caster returned {code} {reason}".rstrip(),
                status_code=int(code) if code.isdigit() else None,
            )
        if status.startswith(b"ICY "):
            self._chunked = False
            return
        headers: dict[bytes, bytes] = {}
        total = len(status) + 2
        while True:
            line = self._line()
            total += len(line) + 2
            if total > 16384:
                raise NtripError("NTRIP response headers exceed 16 KiB")
            if not line:
                break
            name, separator, value = line.partition(b":")
            if not separator:
                raise NtripError("Invalid NTRIP response header")
            headers[name.lower()] = value.strip().lower()
        encoding = headers.get(b"transfer-encoding", b"")
        if encoding and encoding != b"chunked":
            raise NtripError("Unsupported NTRIP transfer encoding")
        self._chunked = encoding == b"chunked"
        self._remaining = 0

    def send_gga(self, sentence: bytes) -> None:
        self._validate_gga(sentence)
        if self._socket is None:
            raise NtripError("NTRIP client is not connected")
        self._socket.sendall(sentence)

    def set_read_timeout(self, seconds: float) -> None:
        if not 0 < seconds < float("inf"):
            raise ValueError("NTRIP read timeout must be finite and positive")
        if self._socket is None:
            raise NtripError("NTRIP client is not connected")
        self._socket.settimeout(seconds)

    @staticmethod
    def _validate_gga(sentence: bytes) -> None:
        if (
            not sentence.startswith(b"$GPGGA,")
            or not sentence.endswith(b"\r\n")
            or any(byte < 32 or byte > 126 for byte in sentence[:-2])
        ):
            raise ValueError("Expected a complete GPGGA sentence")
        try:
            Fix.from_message(parse_ascii(sentence))
        except ProtocolError as error:
            raise ValueError("Expected a valid checksummed GPGGA sentence") from error

    def read(self, size: int = 4096) -> bytes:
        if size <= 0:
            raise ValueError("Read size must be positive")
        if self._socket is None:
            raise NtripError("NTRIP client is not connected")
        if not self._chunked:
            if self._buffer:
                data = bytes(self._buffer[:size])
                del self._buffer[:size]
                return data
            return self._socket.recv(size)
        if self._ended:
            return b""
        if self._need_chunk_terminator:
            if self._take(2) != b"\r\n":
                raise NtripError("Invalid NTRIP chunk terminator")
            self._need_chunk_terminator = False
        if self._remaining == 0:
            line = self._line().split(b";", 1)[0]
            try:
                self._remaining = int(line, 16)
            except ValueError as error:
                raise NtripError("Invalid NTRIP chunk size") from error
            if not 0 <= self._remaining <= 1_048_576:
                raise NtripError("NTRIP chunk exceeds 1 MiB")
            if self._remaining == 0:
                self._ended = True
                return b""
        if not self._buffer:
            self._read_socket()
        data = bytes(self._buffer[: min(size, self._remaining)])
        del self._buffer[: len(data)]
        if not data:
            raise NtripDisconnected("NTRIP chunk ended early")
        self._remaining -= len(data)
        if self._remaining == 0:
            self._need_chunk_terminator = True
        return data

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._buffer.clear()
        self._chunked = False
        self._remaining = 0
        self._need_chunk_terminator = False
        self._ended = False


@dataclass(frozen=True, slots=True)
class Mountpoint:
    """A mountpoint advertised by a caster."""

    name: str
    identifier: str
    format: str
    systems: tuple[str, ...]
    network: str
    country: str
    latitude: float | None
    longitude: float | None
    requires_gga: bool | None
    authentication: str
    fee: str
    bitrate: int | None

    def distance_to(self, latitude: float, longitude: float) -> float | None:
        """Return the great-circle distance in metres, or None for missing location."""
        if self.latitude is None or self.longitude is None:
            return None
        return haversine_distance(latitude, longitude, self.latitude, self.longitude)


def parse_sourcetable(data: str) -> tuple[Mountpoint, ...]:
    """Parse the STR records in a sourcetable, ignoring other record types."""
    sources: list[Mountpoint] = []
    for line in data.splitlines():
        fields = line.split(";")
        if fields[0] != "STR":
            continue
        if len(fields) < 18 or not fields[1]:
            raise NtripError("Invalid NTRIP sourcetable STR record")
        try:
            latitude = float(fields[9]) if fields[9] else None
            longitude = float(fields[10]) if fields[10] else None
            if latitude is not None and (
                not math.isfinite(latitude) or abs(latitude) > 90
            ):
                raise ValueError
            if longitude is not None and (
                not math.isfinite(longitude) or abs(longitude) > 180
            ):
                raise ValueError
            if fields[11] not in ("", "0", "1"):
                raise ValueError
            bitrate = int(fields[17]) if fields[17] else None
            if bitrate is not None and bitrate < 0:
                raise ValueError
        except ValueError as error:
            raise NtripError("Invalid NTRIP sourcetable STR value") from error
        sources.append(
            Mountpoint(
                fields[1],
                fields[2],
                fields[3],
                tuple(filter(None, fields[6].split("+"))),
                fields[7],
                fields[8],
                latitude,
                longitude,
                None if not fields[11] else fields[11] == "1",
                fields[15],
                fields[16],
                bitrate,
            )
        )
    return tuple(sources)


def fetch_sourcetable(
    url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 10.0,
    version: Literal[1, 2] = 2,
    max_bytes: int = 1_048_576,
) -> tuple[Mountpoint, ...]:
    """Fetch a bounded NTRIP v1 or v2 sourcetable from a caster root URL."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    data = bytearray()
    with NtripClient(
        url,
        username=username,
        password=password,
        timeout=timeout,
        version=version,
        _sourcetable=True,
    ) as client:
        while not re.search(rb"(?:^|\n)ENDSOURCETABLE\r?\n", data):
            chunk = client.read(min(4096, max_bytes + 1 - len(data)))
            if not chunk:
                raise NtripDisconnected("Incomplete NTRIP sourcetable")
            data.extend(chunk)
            if len(data) > max_bytes:
                raise NtripError("NTRIP sourcetable exceeds size limit")
    try:
        return parse_sourcetable(data.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise NtripError("Invalid NTRIP sourcetable encoding") from error


class NtripClientPool:
    """Rotate client factories on successive correction connection attempts."""

    def __init__(self, factories: Sequence[Callable[[], NtripClient]]) -> None:
        if not factories or not all(callable(factory) for factory in factories):
            raise ValueError("at least one client factory is required")
        self._factories = tuple(factories)
        self._next = 0
        self._lock = Lock()

    def __call__(self) -> NtripClient:
        with self._lock:
            factory = self._factories[self._next]
            self._next = (self._next + 1) % len(self._factories)
        return factory()
