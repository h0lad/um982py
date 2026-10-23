"""Parses NTRIP requests and streams corrections."""

import asyncio
import base64
import ipaddress
import re
import ssl
from collections import Counter
from dataclasses import dataclass
from time import monotonic
from urllib.parse import unquote_to_bytes

from examples.ntrip_server.auth import Credentials, is_anonymous
from examples.ntrip_server.station import OBSERVATION_TYPES, Station
from examples.ntrip_server.telemetry import Telemetry
from um982py.errors import ProtocolError
from um982py.messages import RtcmMessage

HEADER_LIMIT = 8192


@dataclass(frozen=True, slots=True)
class Limits:
    connections: int = 1024
    per_ip: int = 16
    per_user: int = 32
    queue_frames: int = 32
    header_seconds: float = 5.0
    write_seconds: float = 5.0
    source_seconds: float = 10.0
    frame_seconds: float = 2.0
    coordinate_seconds: float = 30.0
    accepts_per_second: float = 100.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not 0 < value < float("inf"):
                raise ValueError(f"{name} must be finite and positive")


class Bucket:
    def __init__(self, rate: float, *, capacity: float) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.updated = monotonic()

    def take(self, amount: float = 1) -> bool:
        now = monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True


@dataclass(frozen=True, slots=True)
class Request:
    path: str
    version_two: bool
    authorization: str | None
    method: str = "GET"
    if_none_match: str | None = None
    chunked: bool = False
    query: str | None = None


def parse_request(
    raw: bytes, *, website: bool = False, allow_upload: bool = False
) -> Request:
    if len(raw) > HEADER_LIMIT or not raw.endswith(b"\r\n\r\n"):
        raise ProtocolError("invalid request header size or terminator")
    try:
        lines = raw[:-4].decode("ascii").split("\r\n")
    except UnicodeError as error:
        raise ProtocolError("request headers must be ASCII") from error
    parts = lines[0].split(" ")
    source_v1 = allow_upload and len(parts) == 3 and parts[0] == "SOURCE"
    if source_v1:
        if not parts[1] or len(parts[1]) > 256:
            raise ProtocolError("invalid source credential")
        path = parts[2]
    elif (
        len(parts) != 3
        or parts[0]
        not in (
            ("GET", "HEAD")
            if website
            else ("GET", "POST")
            if allow_upload
            else ("GET",)
        )
        or parts[2] not in ("HTTP/1.0", "HTTP/1.1")
    ):
        raise ProtocolError("unsupported HTTP method or version")
    else:
        path = parts[1]
    query = None
    if (
        not website
        and not source_v1
        and parts[0] == "GET"
        and path[:4].lower() == "/%3f"
    ):
        path = "/?" + path[4:]
    if path.startswith("/?") and not source_v1 and parts[0] == "GET" and not website:
        path, encoded_query = path.split("?", 1)
        if not encoded_query or re.search(r"%(?![0-9a-fA-F]{2})", encoded_query):
            raise ProtocolError("invalid sourcetable query")
        try:
            query = unquote_to_bytes(encoded_query).decode("ascii")
        except UnicodeError as error:
            raise ProtocolError("sourcetable query must be ASCII") from error
    path_pattern = (
        r"/(?:[A-Za-z0-9_.-]{1,80})?" if website else r"/(?:[A-Za-z0-9_-]{1,64})?"
    )
    if not re.fullmatch(path_pattern, path):
        raise ProtocolError("invalid request path")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise ProtocolError("invalid header field")
        name, value = name.lower(), value.strip(" \t")
        if name in headers or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ProtocolError("duplicate or invalid header field")
        headers[name] = value
    if not source_v1 and parts[2] == "HTTP/1.1" and not headers.get("host"):
        raise ProtocolError("HTTP/1.1 requires Host")
    post = not source_v1 and parts[0] == "POST"
    if post and (
        parts[2] != "HTTP/1.1"
        or headers.get("ntrip-version") != "Ntrip/2.0"
        or headers.get("transfer-encoding", "").lower() != "chunked"
        or "content-length" in headers
    ):
        raise ProtocolError("NTRIP source POST requires chunked NTRIP 2.0")
    if not post and (
        "transfer-encoding" in headers or headers.get("content-length", "0") != "0"
    ):
        raise ProtocolError("request bodies are not supported")
    if "expect" in headers:
        raise ProtocolError("Expect is not supported")
    version = headers.get("ntrip-version")
    if version not in (None, "Ntrip/2.0"):
        raise ProtocolError("unsupported Ntrip-Version")
    authorization = headers.get("authorization")
    if source_v1:
        encoded = base64.b64encode(f"source:{parts[1]}".encode("ascii")).decode("ascii")
        authorization = f"Basic {encoded}"
    return Request(
        path,
        version is not None,
        authorization,
        method=parts[0],
        if_none_match=headers.get("if-none-match"),
        chunked=post,
        query=query,
    )


class Hub:
    def __init__(self, station: Station, limits: Limits) -> None:
        self.station = station
        self.limits = limits
        self.clients: dict[
            asyncio.StreamWriter, asyncio.Queue[tuple[float, bytes]]
        ] = {}
        self.coordinate: tuple[float, bytes] | None = None
        self.last_observation: float | None = None
        self.frames = 0
        self.slow_clients = 0
        self.telemetry = Telemetry()

    @property
    def is_ready(self) -> bool:
        now = monotonic()
        return (
            self.coordinate is not None
            and now - self.coordinate[0] <= self.limits.coordinate_seconds
            and self.last_observation is not None
            and now - self.last_observation <= self.limits.source_seconds
        )

    def publish(self, message: RtcmMessage) -> None:
        if not self.station.validate_frame(message):
            return
        now = monotonic()
        self.telemetry.record(message, now)
        if message.message_type == 1005:
            self.coordinate = now, message.raw
        elif message.message_type in OBSERVATION_TYPES:
            self.last_observation = now
        self.frames += 1
        if not self.is_ready:
            return
        for writer, queue in tuple(self.clients.items()):
            try:
                queue.put_nowait((now, message.raw))
            except asyncio.QueueFull:
                self.slow_clients += 1
                self.clients.pop(writer, None)
                writer.transport.abort()

    def invalidate(self) -> None:
        self.coordinate = self.last_observation = None
        self.telemetry.invalidate()
        for writer in tuple(self.clients):
            writer.transport.abort()
        self.clients.clear()


class Caster:
    def __init__(
        self,
        hub: Hub,
        credentials: Credentials,
        *,
        public: bool = False,
        source_credentials: Credentials | None = None,
        protect_table: bool = False,
    ) -> None:
        self.hub = hub
        self.credentials = credentials
        self.public = public
        self.source_credentials = source_credentials
        self.protect_table = protect_table
        self.source_active = False
        self.tasks: set[asyncio.Task[None]] = set()
        self.peers: Counter[str] = Counter()
        self.users: Counter[str] = Counter()
        self.accepts = Bucket(hub.limits.accepts_per_second, capacity=100)
        self.auth_attempts = Bucket(4, capacity=8)
        self.auth_slots = asyncio.Semaphore(2)
        self.rejected = 0
        self._tls_context: ssl.SSLContext | None = None

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "unknown"
        if (
            len(self.tasks) >= self.hub.limits.connections
            or self.peers[address] >= self.hub.limits.per_ip
            or not self.accepts.take()
        ):
            self.rejected += 1
            if not self.peers[address]:
                del self.peers[address]
            writer.transport.abort()
            return
        self.peers[address] += 1
        task = asyncio.create_task(self._handle(reader, writer, address))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _reply(
        self,
        writer: asyncio.StreamWriter,
        status: str,
        body: bytes = b"",
        *,
        content_type: str = "text/plain",
        version_two: bool = True,
        sourcetable: bool = False,
    ) -> None:
        protocol = "SOURCETABLE" if sourcetable and not version_two else "HTTP/1.1"
        challenge = (
            'WWW-Authenticate: Basic realm="NTRIP", charset="UTF-8"\r\n'
            if status.startswith("401")
            else ""
        )
        writer.write(
            (
                f"{protocol} {status}\r\nServer: um982py/NtripV2.0\r\n"
                + ("Ntrip-Version: Ntrip/2.0\r\n" if version_two else "")
                + (
                    f"Content-Type: {content_type}\r\nContent-Length: {len(body)}\r\n"
                    f"{challenge}Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                )
            ).encode("ascii")
            + body
        )
        await asyncio.wait_for(writer.drain(), self.hub.limits.write_seconds)

    async def _authorize(self, authorization: str | None) -> str | None:
        if authorization is None:
            return "" if self.public else None
        if self.public and is_anonymous(authorization):
            return ""
        if not self.auth_attempts.take():
            return None
        async with self.auth_slots:
            return await asyncio.to_thread(self.credentials.verify, authorization)

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        address: str,
    ) -> None:
        user: str | None = None
        counted = False
        try:
            if self._tls_context is not None:
                await writer.start_tls(
                    self._tls_context,
                    ssl_handshake_timeout=5,
                    ssl_shutdown_timeout=1,
                )
            try:
                raw = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"), self.hub.limits.header_seconds
                )
                request = parse_request(
                    raw, allow_upload=self.source_credentials is not None
                )
            except (ProtocolError, asyncio.LimitOverrunError):
                await self._reply(writer, "400 Bad Request")
                return
            if request.method in ("SOURCE", "POST"):
                await self._upload(request, reader, writer)
                return
            if request.path == "/" or (
                not request.version_two
                and request.path not in (f"/{self.hub.station.mountpoint}", "/healthz")
            ):
                if (
                    self.protect_table
                    and await self._authorize(request.authorization) is None
                ):
                    await self._reply(writer, "401 Unauthorized")
                    return
                table = self.hub.station.build_sourcetable(public=self.public)
                if request.query is not None:
                    from examples.ntrip_server.filtering import filter_table

                    try:
                        table = filter_table(table, request.query)
                    except ValueError:
                        await self._reply(writer, "400 Bad Request")
                        return
                await self._reply(
                    writer,
                    "200 OK",
                    table,
                    content_type="gnss/sourcetable"
                    if request.version_two
                    else "text/plain",
                    version_two=request.version_two,
                    sourcetable=True,
                )
                return
            if request.path not in (f"/{self.hub.station.mountpoint}", "/healthz"):
                await self._reply(writer, "404 Not Found")
                return
            user = await self._authorize(request.authorization)
            if user is None:
                await self._reply(writer, "401 Unauthorized")
                return
            if user and self.users[user] >= self.hub.limits.per_user:
                await self._reply(writer, "429 Too Many Requests")
                return
            if not self.hub.is_ready:
                await self._reply(writer, "503 Service Unavailable")
                return
            if request.path == "/healthz":
                await self._reply(writer, "200 OK", b"ready\n")
                return
            if user:
                self.users[user] += 1
                counted = True
            await self._stream(reader, writer, request.version_two)
        except (
            OSError,
            TimeoutError,
            asyncio.IncompleteReadError,
            ssl.SSLError,
        ):
            pass
        finally:
            self.hub.clients.pop(writer, None)
            self.peers[address] -= 1
            if not self.peers[address]:
                del self.peers[address]
            if counted and user:
                self.users[user] -= 1
                if not self.users[user]:
                    del self.users[user]
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1.0)
            except (OSError, TimeoutError):
                writer.transport.abort()

    async def _upload(
        self,
        request: Request,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        from examples.ntrip_server.source import _relay_body

        if request.path != f"/{self.hub.station.mountpoint}":
            await self._reply(writer, "404 Not Found")
            return
        credentials = self.source_credentials
        authorization = request.authorization
        if (
            credentials is None
            or authorization is None
            or not self.auth_attempts.take()
        ):
            await self._reply(writer, "401 Unauthorized")
            return
        async with self.auth_slots:
            user = await asyncio.to_thread(credentials.verify, authorization)
        if user is None:
            if request.method == "SOURCE":
                writer.write(b"ERROR - Bad Password\r\n")
                await writer.drain()
            else:
                await self._reply(writer, "401 Unauthorized")
            return
        if self.source_active:
            await self._reply(writer, "409 Conflict")
            return
        self.source_active = True
        try:
            writer.write(
                b"HTTP/1.1 200 OK\r\nNtrip-Version: Ntrip/2.0\r\n"
                b"Content-Length: 0\r\n\r\n"
                if request.chunked
                else b"ICY 200 OK\r\n"
            )
            await asyncio.wait_for(writer.drain(), self.hub.limits.write_seconds)
            await _relay_body(reader, self.hub, request.chunked)
        except (
            OSError,
            ProtocolError,
            ValueError,
            asyncio.IncompleteReadError,
            TimeoutError,
        ):
            self.hub.telemetry.source_failures += 1
        finally:
            self.hub.invalidate()
            self.source_active = False

    async def _stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        version_two: bool,
    ) -> None:
        queue: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue(
            self.hub.limits.queue_frames
        )
        coordinate = self.hub.coordinate
        if coordinate is None:
            return
        queue.put_nowait((monotonic(), coordinate[1]))
        self.hub.clients[writer] = queue
        writer.transport.set_write_buffer_limits(high=16384, low=4096)
        writer.write(
            b"HTTP/1.1 200 OK\r\nServer: um982py/NtripV2.0\r\n"
            b"Ntrip-Version: Ntrip/2.0\r\n"
            b"Content-Type: gnss/data\r\nTransfer-Encoding: chunked\r\n"
            b"Cache-Control: no-store\r\nConnection: close\r\n\r\n"
            if version_two
            else b"ICY 200 OK\r\n"
        )
        sender = asyncio.create_task(self._send(writer, queue, version_two))
        receiver = asyncio.create_task(self._discard_positions(reader))
        try:
            done, _ = await asyncio.wait(
                (sender, receiver), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)

    async def _send(
        self,
        writer: asyncio.StreamWriter,
        queue: asyncio.Queue[tuple[float, bytes]],
        chunked: bool,
    ) -> None:
        while self.hub.is_ready:
            try:
                arrived, raw = await asyncio.wait_for(queue.get(), 1.0)
            except TimeoutError:
                continue
            if monotonic() - arrived > self.hub.limits.frame_seconds:
                return
            writer.write(
                f"{len(raw):X}\r\n".encode("ascii") + raw + b"\r\n" if chunked else raw
            )
            await asyncio.wait_for(writer.drain(), self.hub.limits.write_seconds)
            self.hub.telemetry.sent_bytes += len(raw)
        if chunked:
            writer.write(b"0\r\n\r\n")
            await asyncio.wait_for(writer.drain(), self.hub.limits.write_seconds)

    async def _discard_positions(self, reader: asyncio.StreamReader) -> None:
        budget = Bucket(1024, capacity=4096)
        while data := await reader.read(512):
            if not budget.take(len(data)):
                return

    async def close(self) -> None:
        self.hub.invalidate()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.difference_update(tasks)


async def listen(
    caster: Caster, host: str, port: int, context: ssl.SSLContext | None
) -> asyncio.Server:
    if not ipaddress.ip_address(host).is_loopback and context is None:
        raise ValueError("non-loopback listeners require TLS")
    caster._tls_context = context
    return await asyncio.start_server(
        caster.accept,
        host,
        port,
        limit=HEADER_LIMIT,
        backlog=128,
    )
