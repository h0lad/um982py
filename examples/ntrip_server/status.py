"""Serves public station status and HTTP resources."""

import asyncio
import hashlib
import ipaddress
import json
import re
import ssl
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import formatdate
from enum import StrEnum
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from examples.ntrip_server.caster import Bucket, Caster, parse_request
from examples.ntrip_server.station import RTCM_INTERVALS
from um982py.errors import ProtocolError

HEADER_LIMIT = 2048
SECURITY_HEADERS = (
    "Content-Security-Policy: default-src 'none'; script-src 'self'; "
    "style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; "
    "object-src 'none'; frame-ancestors 'none'; form-action 'none'; "
    "require-trusted-types-for 'script'\r\n"
    "X-Content-Type-Options: nosniff\r\nX-Frame-Options: DENY\r\n"
    "Referrer-Policy: no-referrer\r\nCross-Origin-Resource-Policy: same-origin\r\n"
    "Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()\r\n"
)
MESSAGE_NAMES = {
    1005: "Reference position",
    1074: "GPS MSM4",
    1094: "Galileo MSM4",
    1124: "BeiDou MSM4",
}


class State(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    WAITING = "waiting"


def validate_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or any(ord(char) <= 32 or ord(char) >= 127 for char in value)
    ):
        raise ValueError("status caster URL must be an origin without credentials")
    try:
        address = ipaddress.ip_address(host)
        loopback = address.is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
        if len(host) > 253 or any(
            not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.rstrip(".").split(".")
        ):
            raise ValueError("status caster URL has an invalid host") from None
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("status caster URL requires HTTPS outside loopback")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("status caster URL has an invalid port")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class StatusSettings:
    caster_url: str
    contact_url: str | None = None
    relay: bool = False
    connections: int = 64
    per_ip: int = 8

    def __post_init__(self) -> None:
        validate_endpoint(self.caster_url)
        if not 1 <= self.per_ip <= self.connections <= 4096:
            raise ValueError("status budgets need 1 <= per-IP <= connections <= 4096")
        if self.contact_url is not None:
            parsed = urlsplit(self.contact_url)
            validate_endpoint(f"{parsed.scheme}://{parsed.netloc}")
            if parsed.scheme != "https" or any(
                ord(char) <= 32 or ord(char) >= 127 for char in self.contact_url
            ):
                raise ValueError("status contact URL must be an ASCII HTTPS URL")


@dataclass(frozen=True, slots=True)
class Resource:
    body: bytes
    content_type: str
    cache_control: str
    etag: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "etag", '"' + hashlib.sha256(self.body).hexdigest() + '"'
        )


def build_snapshot(
    caster: Caster, settings: StatusSettings, now: float
) -> dict[str, object]:
    hub, station = caster.hub, caster.hub.station
    telemetry = hub.telemetry
    telemetry.sample(now, ready=hub.is_ready)
    received_bps, sent_bps = telemetry.calculate_bitrates(now)
    messages: list[dict[str, object]] = []
    for kind, interval in RTCM_INTERVALS:
        sample = telemetry.messages.get(kind)
        age = max(0, now - sample.received) if sample else None
        fresh = bool(
            sample
            and sample.current
            and age is not None
            and age <= max(10, 3 * interval)
        )
        messages.append(
            {
                "type": kind,
                "name": MESSAGE_NAMES[kind],
                "interval_seconds": interval,
                "age_seconds": round(age, 2) if age is not None else None,
                "fresh": fresh,
                "frames": sample.count if sample else 0,
                "bytes": sample.bytes_received if sample else 0,
                "satellites": sample.satellites if sample and fresh else None,
                "signals": sample.signals if sample and fresh else None,
            }
        )
    ready = hub.is_ready
    if ready:
        state = (
            State.ONLINE
            if all(message["fresh"] for message in messages)
            else State.DEGRADED
        )
    else:
        state = State.OFFLINE if telemetry.received_bytes else State.WAITING
    connection = urlsplit(settings.caster_url)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "valid_for_seconds": 15,
        "state": state,
        "ready": ready,
        "station": {
            "mountpoint": station.mountpoint,
            "station_id": station.station_id,
            "country": station.country,
            "latitude": round(station.latitude, 5),
            "longitude": round(station.longitude, 5),
            "height_m": round(station.height, 1),
            "reference_frame": station.reference_frame,
            "coordinate_epoch": station.coordinate_epoch,
            "reference_point": "ARP",
            "position_reviewed": station.position_verified,
        },
        "connection": {
            "url": settings.caster_url.rstrip("/") + "/" + station.mountpoint,
            "host": connection.hostname,
            "port": connection.port or (443 if connection.scheme == "https" else 80),
            "tls": connection.scheme == "https",
            "public": caster.public,
            "protocols": ["NTRIP 1.0", "NTRIP 2.0"],
            "format": "RTCM 3.2 / MSM4",
            "constellations": ["GPS", "Galileo", "BeiDou"],
            "gga_required": False,
            "contact_url": settings.contact_url,
        },
        "service": {
            "source": "relay" if settings.relay else "serial",
            "uptime_seconds": round(now - telemetry.started, 1),
            "observation_age_seconds": (
                round(max(0, now - hub.last_observation), 2)
                if hub.last_observation is not None
                else None
            ),
            "coordinate_age_seconds": (
                round(max(0, now - hub.coordinate[0]), 2) if hub.coordinate else None
            ),
            "source_bps": received_bps,
            "output_bps": sent_bps,
            "frames": hub.frames,
            "received_bytes": telemetry.received_bytes,
            "sent_bytes": telemetry.sent_bytes,
            "source_failures": telemetry.source_failures,
            "streams": len(hub.clients),
            "connections": len(caster.tasks),
            "max_connections": hub.limits.connections,
            "per_ip_limit": hub.limits.per_ip,
            "per_user_limit": hub.limits.per_user,
            "slow_clients": hub.slow_clients,
            "admission_rejections": caster.rejected,
        },
        "messages": messages,
        "availability": telemetry.build_availability(now),
        "quality": {
            "rover_accuracy_m": None,
            "receiver_cn0_dbhz": None,
            "dop": None,
            "correction_epoch_latency_seconds": None,
        },
    }


class StatusSite:
    def __init__(self, caster: Caster, settings: StatusSettings) -> None:
        self.caster = caster
        self.settings = settings
        directory = Path(__file__).with_name("web")
        self.resources = {
            path: Resource(
                (directory / name).read_bytes(),
                content_type,
                "public, max-age=300, must-revalidate",
            )
            for path, name, content_type in (
                ("/", "index.html", "text/html; charset=utf-8"),
                ("/app.js", "app.js", "text/javascript; charset=utf-8"),
                ("/style.css", "style.css", "text/css; charset=utf-8"),
                ("/favicon.svg", "favicon.svg", "image/svg+xml"),
            )
        }
        self.resources["/"] = Resource(
            self.resources["/"].body,
            "text/html; charset=utf-8",
            "public, max-age=5, must-revalidate",
        )
        self.resources["/sourcetable.txt"] = Resource(
            caster.hub.station.build_sourcetable(public=caster.public),
            "text/plain; charset=utf-8",
            "public, max-age=60, must-revalidate",
        )
        self.tasks: set[asyncio.Task[None]] = set()
        self.peers: Counter[str] = Counter()
        self.admission = Bucket(50, capacity=100)
        self.secure = False
        self._tls_context: ssl.SSLContext | None = None
        self.is_ready = False
        self.rejected = 0
        self.refresh()

    def refresh(self) -> None:
        data = build_snapshot(self.caster, self.settings, monotonic())
        self.is_ready = data["ready"] is True
        self.resources["/status.json"] = Resource(
            json.dumps(
                data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            ).encode("ascii"),
            "application/json; charset=utf-8",
            "public, max-age=1, s-maxage=1, must-revalidate",
        )

    async def update(self) -> None:
        while True:
            self.refresh()
            await asyncio.sleep(1)

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "unknown"
        if (
            len(self.tasks) >= self.settings.connections
            or self.peers[address] >= self.settings.per_ip
            or not self.admission.take()
        ):
            self.rejected += 1
            writer.transport.abort()
            return
        self.peers[address] += 1
        task = asyncio.create_task(self._handle(reader, writer, address))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, address: str
    ) -> None:
        method = "GET"
        try:
            if self._tls_context is not None:
                await writer.start_tls(
                    self._tls_context,
                    ssl_handshake_timeout=5,
                    ssl_shutdown_timeout=1,
                )
            try:
                raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
                if len(raw) > HEADER_LIMIT:
                    raise ProtocolError("header too large")
                request = parse_request(raw, website=True)
            except (ProtocolError, asyncio.LimitOverrunError):
                await self._reply(
                    writer,
                    "400 Bad Request",
                    Resource(b"Bad request\n", "text/plain", "no-store"),
                    method,
                )
                return
            method = request.method
            if request.path == "/healthz":
                await self._reply(
                    writer,
                    "200 OK" if self.is_ready else "503 Service Unavailable",
                    Resource(
                        b"ready\n" if self.is_ready else b"unavailable\n",
                        "text/plain",
                        "no-store",
                    ),
                    method,
                )
                return
            resource = self.resources.get(request.path)
            if resource is None:
                await self._reply(
                    writer,
                    "404 Not Found",
                    Resource(b"Not found\n", "text/plain", "no-store"),
                    method,
                )
                return
            tags = (request.if_none_match or "").split(",")
            unchanged = any(
                tag.strip() in ("*", resource.etag, "W/" + resource.etag)
                for tag in tags
            )
            await self._reply(
                writer, "304 Not Modified" if unchanged else "200 OK", resource, method
            )
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            self.peers[address] -= 1
            if not self.peers[address]:
                del self.peers[address]
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                writer.transport.abort()

    async def _reply(
        self, writer: asyncio.StreamWriter, status: str, resource: Resource, method: str
    ) -> None:
        transport_security = (
            "Strict-Transport-Security: max-age=31536000\r\n" if self.secure else ""
        )
        writer.write(
            (
                f"HTTP/1.1 {status}\r\nDate: {formatdate(usegmt=True)}\r\n"
                f"Content-Type: {resource.content_type}\r\n"
                f"Content-Length: {len(resource.body)}\r\n"
                f"ETag: {resource.etag}\r\nCache-Control: {resource.cache_control}\r\n"
                f"{SECURITY_HEADERS}{transport_security}Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        if method != "HEAD" and not status.startswith("304"):
            writer.write(resource.body)
        await asyncio.wait_for(writer.drain(), 2)

    async def close(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.difference_update(tasks)


async def listen_status(
    site: StatusSite, host: str, port: int, context: ssl.SSLContext | None = None
) -> asyncio.Server:
    if not ipaddress.ip_address(host).is_loopback and context is None:
        raise ValueError("non-loopback status listeners require TLS")
    site.secure = context is not None
    site._tls_context = context
    return await asyncio.start_server(
        site.accept, host, port, limit=HEADER_LIMIT, backlog=64
    )
