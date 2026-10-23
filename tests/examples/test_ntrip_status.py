"""Checks telemetry privacy, bounded HTTP service and status freshness."""

import asyncio
import json
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from time import monotonic
from unittest.mock import MagicMock

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, Limits, listen, parse_request
from examples.ntrip_server.status import (
    StatusSettings,
    StatusSite,
    build_snapshot,
    listen_status,
    validate_endpoint,
)
from examples.ntrip_server.telemetry import Telemetry, count_msm_masks

from tests.examples.test_ntrip_server import (
    ACCESS,
    chunk,
    coordinate_frame,
    observation_frame,
    ready_hub,
    running,
)
from tests.examples.test_ntrip_server import request as ntrip_request
from tests.examples.test_ntrip_server import station as station
from tests.examples.test_ntrip_server import tls_files as tls_files
from um982py.errors import ProtocolError


@asynccontextmanager
async def website(
    station: Station,
    *,
    settings: StatusSettings | None = None,
    context: ssl.SSLContext | None = None,
) -> AsyncIterator[tuple[StatusSite, int]]:
    caster = Caster(ready_hub(station), Credentials({}), public=True)
    site = StatusSite(
        caster, settings or StatusSettings("https://caster.example.org:2101")
    )
    server = await listen_status(site, "127.0.0.1", 0, context)
    try:
        async with server:
            yield site, server.sockets[0].getsockname()[1]
    finally:
        await site.close()
        await caster.close()


async def get(
    port: int,
    path: str = "/",
    *,
    method: str = "GET",
    headers: str = "",
    context: ssl.SSLContext | None = None,
) -> tuple[str, dict[str, str], bytes]:
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        port,
        ssl=context,
        server_hostname="localhost" if context else None,
    )
    try:
        writer.write(
            f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n".encode()
        )
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), 3)
    finally:
        writer.close()
        await writer.wait_closed()
    header, body = raw.split(b"\r\n\r\n", 1)
    lines = header.decode("ascii").split("\r\n")
    fields = dict(line.lower().split(": ", 1) for line in lines[1:])
    return lines[0], fields, body


def test_endpoint_configuration_rejects_credentials_and_unsafe_origins() -> None:
    for value in (
        "http://caster.example.org:2101",
        "javascript:alert(1)",
        "https://user:password@caster.example.org",
        "https://caster.example.org/MOUNT",
        "https://caster.example.org/?x=1",
        "https://caster.example.org/#fragment",
        "https://caster.example.org:0",
        "https://caster.example.org:65536",
        "https://caster.example.org\r\nX: poisoned",
        "https://caster.example.org\\evil",
    ):
        with pytest.raises(ValueError):
            validate_endpoint(value)
    assert (
        validate_endpoint("https://caster.example.org:2101/")
        == "https://caster.example.org:2101"
    )
    assert validate_endpoint("http://127.0.0.1:2101") == "http://127.0.0.1:2101"
    assert validate_endpoint("https://[::1]:2101") == "https://[::1]:2101"
    with pytest.raises(ValueError):
        StatusSettings("https://caster.example.org", "javascript:alert(1)")


def test_msm_masks_are_counted_independently_of_signal_quality() -> None:
    satellite_mask = (1 << 63) | (1 << 62) | (1 << 21) | 1
    signal_mask = (1 << 31) | (1 << 10)
    header = f"{1074:012b}{42:012b}{123000:030b}{0:019b}"
    assert len(header) == 73
    bits = header + f"{satellite_mask:064b}{signal_mask:032b}" + "0" * 7
    payload = int(bits, 2).to_bytes(22, "big")
    assert count_msm_masks(payload) == (4, 2)
    assert count_msm_masks(bytes(21)) == (None, None)


def test_telemetry_retains_constant_space_and_marks_session_discontinuities(
    station: Station,
) -> None:
    telemetry = Telemetry()
    started = telemetry.started
    message = observation_frame(station)
    for index in range(10000):
        telemetry.record(message, started + index)
        telemetry.sample(started + index, ready=index % 2 == 0)
    assert len(telemetry.messages) == 1
    assert len(telemetry.history) == 900
    assert len(telemetry.rates) == 6
    assert telemetry.messages[1074].count == 10000
    build_availability = telemetry.build_availability(started + 9999)
    assert build_availability["ready_percent"] == 50
    assert len(build_availability["buckets"]) == 60
    telemetry.invalidate()
    assert not telemetry.messages[1074].current
    assert telemetry.messages[1074].satellites is None
    assert telemetry.messages[1074].count == 10000


def test_receipt_rates_and_unobserved_gaps_are_not_fabricated(station: Station) -> None:
    telemetry = Telemetry()
    started = telemetry.started
    telemetry.sample(started, ready=True)
    telemetry.record(observation_frame(station), started + 0.5)
    telemetry.sample(started + 1, ready=True)
    assert (
        telemetry.calculate_bitrates(started + 1)[0]
        == len(observation_frame(station).raw) * 8
    )
    telemetry.sample(started + 100, ready=False)
    assert telemetry.calculate_bitrates(started + 100) == (0, 0)
    build_availability = telemetry.build_availability(started + 100)
    assert build_availability["sample_count"] == 3
    assert None in build_availability["buckets"]
    assert len(telemetry.rates) == 1


def test_public_snapshot_is_an_allowlist_without_accounts_or_local_paths(
    station: Station,
) -> None:
    station = replace(
        station, source_report="/private/secret-report.sum", latitude=50.123456789
    )
    caster = Caster(
        ready_hub(station), Credentials({"hidden-user": hash_password(ACCESS)})
    )
    caster.peers["192.0.2.123"] = 2
    caster.users["hidden-user"] = 1
    data = build_snapshot(
        caster, StatusSettings("https://caster.example.org:2101"), monotonic()
    )
    encoded = json.dumps(data)
    for forbidden in ("hidden-user", "192.0.2.123", "secret-report", ACCESS, "scrypt$"):
        assert forbidden not in encoded
    assert data["station"]["latitude"] == 50.12346
    assert data["quality"]["rover_accuracy_m"] is None
    assert data["quality"]["correction_epoch_latency_seconds"] is None
    assert data["connection"]["public"] is False
    assert data["state"] == "degraded"
    caster.hub.invalidate()
    data = build_snapshot(
        caster, StatusSettings("https://caster.example.org:2101"), monotonic()
    )
    assert data["state"] == "offline"
    assert data["ready"] is False
    assert not any(row["fresh"] for row in data["messages"])


def test_static_assets_and_json_have_security_headers_and_no_cookies(
    station: Station,
) -> None:
    async def scenario() -> None:
        async with website(station) as (_, port):
            for path in (
                "/",
                "/app.js",
                "/style.css",
                "/favicon.svg",
                "/status.json",
                "/sourcetable.txt",
            ):
                status, headers, body = await get(port, path)
                assert status == "HTTP/1.1 200 OK"
                assert len(body) == int(headers["content-length"])
                assert "frame-ancestors 'none'" in headers["content-security-policy"]
                assert "'unsafe-inline'" not in headers["content-security-policy"]
                assert headers["x-content-type-options"] == "nosniff"
                assert headers["cross-origin-resource-policy"] == "same-origin"
                assert "set-cookie" not in headers
                assert "access-control-allow-origin" not in headers
            _, _, body = await get(port, "/status.json")
            assert json.loads(body)["station"]["mountpoint"] == station.mountpoint

    asyncio.run(scenario())


def test_conditional_requests_and_head_reuse_the_cached_snapshot(
    station: Station, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        async with website(station) as (site, port):
            resource = site.resources["/status.json"]
            replacement = MagicMock(
                side_effect=AssertionError("serialized per request")
            )
            monkeypatch.setattr(site, "refresh", replacement)
            status, headers, body = await get(port, "/status.json")
            assert body is resource.body or body == resource.body
            for method in ("GET", "HEAD"):
                status, cached_headers, body = await get(
                    port,
                    "/status.json",
                    method=method,
                    headers=f"If-None-Match: {headers['etag']}\r\n",
                )
                assert status == "HTTP/1.1 304 Not Modified"
                assert body == b""
                assert cached_headers["etag"] == resource.etag
            status, _, body = await get(port, "/", method="HEAD")
            assert status == "HTTP/1.1 200 OK"
            assert body == b""
            replacement.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "wire_request",
    [
        "POST / HTTP/1.1\r\nHost: localhost\r\n\r\n",
        "GET /../auth.py HTTP/1.1\r\nHost: localhost\r\n\r\n",
        "GET /%2e%2e/auth.py HTTP/1.1\r\nHost: localhost\r\n\r\n",
        "GET / HTTP/1.1\r\nContent-Length: 1\r\n\r\nx",
        "GET / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
        "GET / HTTP/1.1\r\nHost: first\r\nHost: second\r\n\r\n",
        "GET / HTTP/1.1\r\nX: " + "a" * 2100 + "\r\n\r\n",
    ],
)
def test_website_rejects_ambiguous_requests_and_never_reads_paths(
    station: Station, wire_request: str
) -> None:
    async def scenario() -> None:
        async with website(station) as (_, port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(wire_request.encode())
            await writer.drain()
            result = await asyncio.wait_for(reader.read(), 2)
            assert result.startswith(b"HTTP/1.1 400 Bad Request")
            writer.close()
            await writer.wait_closed()

    asyncio.run(scenario())


def test_health_tracks_outage_and_site_budget_does_not_consume_caster_capacity(
    station: Station,
) -> None:
    async def scenario() -> None:
        settings = StatusSettings("https://caster.example.org", connections=1, per_ip=1)
        async with website(station, settings=settings) as (site, port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /")
            await writer.drain()
            second, other = await asyncio.open_connection("127.0.0.1", port)
            assert await asyncio.wait_for(second.read(), 1) == b""
            assert site.rejected == 1
            assert len(site.caster.tasks) == 0
            assert site.caster.hub.is_ready
            other.close()
            await other.wait_closed()
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(reader.read(), 1)
            await site.close()
        async with website(station) as (site, port):
            status, _, _ = await get(port, "/healthz")
            assert status == "HTTP/1.1 200 OK"
            site.caster.hub.invalidate()
            site.refresh()
            status, headers, _ = await get(port, "/healthz")
            assert status == "HTTP/1.1 503 Service Unavailable"
            assert headers["cache-control"] == "no-store"

    asyncio.run(scenario())


def test_status_tls_and_ntrip_request_paths_remain_separate(
    station: Station, tls_files: tuple[Path, Path]
) -> None:
    async def scenario() -> None:
        cert, key = tls_files
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert, key)
        client_context = ssl.create_default_context(cafile=cert)
        async with website(station, context=server_context) as (_, port):
            status, headers, _ = await get(port, context=client_context)
            assert status == "HTTP/1.1 200 OK"
            assert "max-age=" in headers["strict-transport-security"]
        caster = Caster(ready_hub(station), Credentials({}), public=True)
        site = StatusSite(caster, StatusSettings("https://caster.example.org"))
        with pytest.raises(ValueError, match="TLS"):
            await listen_status(site, "192.0.2.1", 0)
        with pytest.raises(ProtocolError):
            parse_request(b"GET /status.json HTTP/1.1\r\n\r\n")
        with pytest.raises(ProtocolError):
            parse_request(b"HEAD / HTTP/1.1\r\n\r\n")

    asyncio.run(scenario())


@pytest.mark.parametrize("is_website", [False, True])
@pytest.mark.parametrize("per_ip", [1, 2])
def test_tls_handshakes_use_connection_and_peer_budgets(
    station: Station,
    tls_files: tuple[Path, Path],
    *,
    is_website: bool,
    per_ip: int,
) -> None:
    async def scenario() -> None:
        cert, key = tls_files
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        connections = 2 if per_ip == 1 else 1
        service = (
            website(
                station,
                settings=StatusSettings(
                    "https://caster.example.org",
                    connections=connections,
                    per_ip=min(per_ip, connections),
                ),
                context=context,
            )
            if is_website
            else running(
                station,
                limits=Limits(connections=connections, per_ip=per_ip),
                context=context,
            )
        )
        async with service as (listener, port):
            _, pending = await asyncio.open_connection("127.0.0.1", port)
            reader, rejected = await asyncio.open_connection(
                "127.0.0.1",
                port,
                local_addr=("127.0.0.1" if per_ip == 1 else "127.0.0.2", 0),
            )
            try:
                assert await asyncio.wait_for(reader.read(), 1) == b""
                assert listener.rejected == 1
                assert len(listener.tasks) == 1
            finally:
                rejected.close()
                pending.close()
                await rejected.wait_closed()
                await pending.wait_closed()
            await asyncio.wait_for(asyncio.gather(*tuple(listener.tasks)), 1)
            assert not listener.peers
            reader, writer = await asyncio.open_connection(
                "127.0.0.1",
                port,
                ssl=ssl.create_default_context(cafile=cert),
                server_hostname="localhost",
            )
            try:
                writer.write(
                    b"GET / HTTP/1.1\r\nHost: localhost\r\n"
                    b"Ntrip-Version: Ntrip/2.0\r\n\r\n"
                )
                await writer.drain()
                assert await asyncio.wait_for(reader.readline(), 1) == (
                    b"HTTP/1.1 200 OK\r\n"
                )
            finally:
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())


def test_status_fanout_reuses_one_snapshot_while_corrections_keep_flowing(
    station: Station,
) -> None:
    async def scenario() -> None:
        settings = StatusSettings(
            "https://caster.example.org", connections=64, per_ip=64
        )
        async with website(station, settings=settings) as (site, port):
            server = await listen(site.caster, "127.0.0.1", 0, None)
            async with server:
                ntrip_port = server.sockets[0].getsockname()[1]
                reader, writer, _ = await ntrip_request(ntrip_port, b"/TEST01")
                assert await chunk(reader) == coordinate_frame(station).raw
                resource = site.resources["/status.json"]
                requests = [
                    asyncio.create_task(get(port, "/status.json")) for _ in range(64)
                ]
                message = observation_frame(station)
                site.caster.hub.publish(message)
                responses = await asyncio.gather(*requests)
                assert all(status == "HTTP/1.1 200 OK" for status, _, _ in responses)
                assert all(body == resource.body for _, _, body in responses)
                assert await asyncio.wait_for(chunk(reader), 1) == message.raw
                assert site.rejected == 0
                assert site.caster.hub.slow_clients == 0
                assert site.caster.hub.telemetry.sent_bytes >= len(message.raw)
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())
