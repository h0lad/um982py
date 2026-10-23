"""Reads receiver and TLS upstream sources."""

import asyncio
import base64
import logging
import re
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic

from examples.ntrip_server.caster import HEADER_LIMIT, Hub
from examples.ntrip_server.station import OBSERVATION_TYPES
from um982py import AsyncReceiver
from um982py.commands import logging as receiver_logging
from um982py.errors import ProtocolError, ResponseTimeout, UM982Error
from um982py.messages import RtcmMessage
from um982py.protocol import StreamDecoder

LOGGER = logging.getLogger(__name__)

_CHUNK_LINE = re.compile(
    rb"([0-9A-Fa-f]+)(?:[ \t]*;[ \t]*[!#$%&'*+.^_`|~0-9A-Za-z-]+"
    rb"(?:[ \t]*=[ \t]*(?:[!#$%&\'*+.^_`|~0-9A-Za-z-]+"
    rb'|"(?:[\t !#-\[\]-~\x80-\xff]|\\[\t -~\x80-\xff])*"))?)*[ \t]*'
)


async def read_receiver(hub: Hub, port: str, baud: int, *, timeout: float = 3) -> None:
    async with await AsyncReceiver.connect(port, baud, timeout=timeout) as receiver:
        await receiver.execute(receiver_logging.stop())
        deadline = monotonic() + 2
        while monotonic() < deadline:
            try:
                await receiver.receive(timeout=0.1)
            except ResponseTimeout:
                break
        else:
            raise ValueError("receiver output did not stop on the dedicated port")
        for command in hub.station.build_commands():
            await receiver.execute(command)
        last_observation = monotonic()
        while True:
            if monotonic() - last_observation > hub.limits.source_seconds:
                raise OSError("receiver observation stream stalled")
            try:
                message = await receiver.receive(timeout=1.0)
            except ResponseTimeout:
                continue
            if isinstance(message, RtcmMessage):
                hub.publish(message)
                if message.message_type in OBSERVATION_TYPES:
                    last_observation = monotonic()


@dataclass(frozen=True, slots=True)
class Upstream:
    host: str
    port: int
    username: str
    password: str
    context: ssl.SSLContext


async def _relay_body(reader: asyncio.StreamReader, hub: Hub, chunked: bool) -> None:
    decoder = StreamDecoder(max_frame_size=4096)
    last_observation = monotonic()
    remaining = 0
    while True:
        async with asyncio.timeout(hub.limits.source_seconds):
            if chunked:
                if not remaining:
                    line = await reader.readuntil(b"\r\n")
                    match = _CHUNK_LINE.fullmatch(line[:-2])
                    if not match or len(line) > HEADER_LIMIT or len(match[1]) > 16:
                        raise ProtocolError("upstream sent an invalid chunk size")
                    remaining = int(match[1], 16)
                    if not remaining:
                        trailer_size = 0
                        while True:
                            trailer = await reader.readuntil(b"\r\n")
                            trailer_size += len(trailer)
                            if trailer_size > HEADER_LIMIT:
                                raise ProtocolError("upstream trailers are too large")
                            if trailer == b"\r\n":
                                raise OSError("upstream ended the stream")
                            if b":" not in trailer:
                                raise ProtocolError("upstream sent an invalid trailer")
                data = await reader.readexactly(min(remaining, 4096))
                remaining -= len(data)
                if not remaining and await reader.readexactly(2) != b"\r\n":
                    raise ProtocolError("upstream chunk terminator is invalid")
            else:
                data = await reader.read(4096)
                if not data:
                    raise OSError("upstream disconnected")
        for message in decoder.feed(data):
            if isinstance(message, RtcmMessage):
                hub.publish(message)
                if message.message_type in OBSERVATION_TYPES:
                    last_observation = monotonic()
        if monotonic() - last_observation > hub.limits.source_seconds:
            raise OSError("upstream has no recent observations")


async def read_upstream(hub: Hub, upstream: Upstream) -> None:
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection(
            upstream.host,
            upstream.port,
            ssl=upstream.context,
            server_hostname=upstream.host,
            ssl_handshake_timeout=5,
            limit=HEADER_LIMIT,
        )
    try:
        token = base64.b64encode(
            f"{upstream.username}:{upstream.password}".encode()
        ).decode("ascii")
        writer.write(
            (
                f"GET /{hub.station.mountpoint} HTTP/1.1\r\n"
                f"Host: {upstream.host}:{upstream.port}\r\n"
                "Ntrip-Version: Ntrip/2.0\r\nUser-Agent: NTRIP um982py/1.0\r\n"
                f"Authorization: Basic {token}\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
        )
        async with asyncio.timeout(10):
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
        if len(header) > HEADER_LIMIT:
            raise ProtocolError("upstream header is too large")
        lines = header[:-4].decode("ascii").split("\r\n")
        if lines[0] not in ("HTTP/1.1 200 OK", "HTTP/1.0 200 OK"):
            raise OSError("upstream refused the correction stream")
        fields: dict[str, str] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if not separator or name.lower() in fields:
                raise ProtocolError("upstream sent ambiguous headers")
            fields[name.lower()] = value.strip().lower()
        encoding = fields.get("transfer-encoding")
        if encoding not in (None, "chunked") or "content-length" in fields:
            raise ProtocolError("unsupported upstream transfer framing")
        if fields.get("content-encoding", "identity") != "identity":
            raise ProtocolError("upstream compression is not supported")
        await _relay_body(reader, hub, encoding == "chunked")
    except asyncio.LimitOverrunError as error:
        raise ProtocolError(
            "upstream exceeded the header or chunk-line limit"
        ) from error
    except UnicodeError as error:
        raise ProtocolError("upstream headers must be ASCII") from error
    finally:
        writer.close()
        with suppress(OSError, TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), 1.0)


async def supervise(hub: Hub, operation: Callable[[], Awaitable[None]]) -> None:
    delay = 1.0
    try:
        while True:
            started = monotonic()
            try:
                await operation()
                raise OSError("source ended")
            except (OSError, UM982Error, asyncio.IncompleteReadError) as error:
                hub.telemetry.source_failures += 1
                hub.invalidate()
                LOGGER.warning(
                    "source unavailable (%s); retrying", type(error).__name__
                )
                if monotonic() - started > 60:
                    delay = 1.0
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
    finally:
        hub.invalidate()
