"""Checks protocol, isolation, authentication and geodetic behaviour."""

import argparse
import asyncio
import base64
import json
import shutil
import ssl
import subprocess
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, MagicMock

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.__main__ import create_tls_context
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, Hub, Limits, listen, parse_request
from examples.ntrip_server.source import (
    Upstream,
    read_receiver,
    read_upstream,
    supervise,
)
from examples.ntrip_server.survey import capture_survey, export_survey

from tests.examples._new_api import observation, record
from um982py.commands import modes
from um982py.errors import ProtocolError, ResponseTimeout
from um982py.geodesy import ecef_from_geodetic
from um982py.messages import RtcmMessage
from um982py.protocol import StreamDecoder
from um982py.protocol.binary import parse_rtcm
from um982py.protocol.checksums import rtcm_crc24q

ACCESS = "a long synthetic test credential"


@pytest.fixture
def station() -> Station:
    return Station(
        mountpoint="TEST01",
        station_id=42,
        latitude=50.0,
        longitude=8.0,
        height=123.4,
        reference_frame="ITRF2020",
        coordinate_epoch=2026.8,
        source_report="synthetic-test.sum",
        position_verified=True,
    )


def frame(payload: bytes) -> RtcmMessage:
    header = b"\xd3" + len(payload).to_bytes(2, "big")
    raw = header + payload
    return parse_rtcm(raw + rtcm_crc24q(raw).to_bytes(3, "big"))


def coordinate_frame(station: Station, *, delta: float = 0) -> RtcmMessage:
    coordinates = ecef_from_geodetic(
        station.latitude, station.longitude, station.height
    )
    value = (1005 << 140) | (station.station_id << 128)
    for start, coordinate in zip((34, 74, 114), coordinates, strict=True):
        scaled = round((coordinate + delta) * 10000) & ((1 << 38) - 1)
        value |= scaled << (152 - start - 38)
    return frame(value.to_bytes(19, "big"))


def observation_frame(station: Station) -> RtcmMessage:
    return frame(((1074 << 12) | station.station_id).to_bytes(3, "big") + bytes(19))


def ready_hub(station: Station, limits: Limits | None = None) -> Hub:
    hub = Hub(station, limits or Limits())
    hub.publish(coordinate_frame(station))
    hub.publish(observation_frame(station))
    return hub


def authorization(user: str = "rover", credential: str = ACCESS) -> bytes:
    encoded = base64.b64encode(f"{user}:{credential}".encode())
    return b"Authorization: Basic " + encoded + b"\r\n"


@asynccontextmanager
async def running(
    station: Station,
    *,
    public: bool = True,
    limits: Limits | None = None,
    users: dict[str, str] | None = None,
    context: ssl.SSLContext | None = None,
) -> AsyncIterator[tuple[Caster, int]]:
    caster = Caster(ready_hub(station, limits), Credentials(users or {}), public=public)
    server = await listen(caster, "127.0.0.1", 0, context)
    try:
        async with server:
            yield caster, server.sockets[0].getsockname()[1]
    finally:
        await caster.close()


async def request(
    port: int, path: bytes, headers: bytes = b"", *, version_two: bool = True
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET "
        + path
        + b" HTTP/1.1\r\nHost: localhost\r\n"
        + (b"Ntrip-Version: Ntrip/2.0\r\n" if version_two else b"")
        + headers
        + b"\r\n"
    )
    await writer.drain()
    header = await asyncio.wait_for(reader.readuntil(b"\r\n"), 2)
    if not header.startswith(b"ICY "):
        header += await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
    return reader, writer, header


async def chunk(reader: asyncio.StreamReader) -> bytes:
    size = int(await asyncio.wait_for(reader.readuntil(b"\r\n"), 2), 16)
    data = await reader.readexactly(size)
    assert await reader.readexactly(2) == b"\r\n"
    return data


def test_station_refuses_unreviewed_positions_and_ambiguous_mounts(
    station: Station, tmp_path: Path
) -> None:
    for fields in (
        {"position_verified": False},
        {"reference_point": "marker"},
        {"height": float("nan")},
        {"latitude": float("inf")},
        {"station_id": True},
        {"mountpoint": "bad\r\nMount"},
        {"coordinate_epoch": 1900},
    ):
        with pytest.raises(ValueError):
            replace(station, **fields)
    path = tmp_path / "station.json"
    path.write_text(json.dumps(asdict(station)))
    assert Station.load(path) == station
    path.write_text(json.dumps({**asdict(station), "unknown": 1}))
    with pytest.raises(ValueError, match="invalid fields"):
        Station.load(path)


def test_station_uses_fixed_coordinates_without_survey_or_flash_writes(
    station: Station,
) -> None:
    commands = [command.text for command in station.build_commands()]
    ecef = ecef_from_geodetic(station.latitude, station.longitude, station.height)
    assert commands == [
        modes.base_ecef(*ecef, station_id=42).text,
        "CONFIG ANTENNADELTAHEN 0 0 0",
        "RTCM1005 5",
        "RTCM1074 1",
        "RTCM1094 1",
        "RTCM1124 1",
    ]
    assert b";N;N;9600;" in station.build_sourcetable(public=True)
    assert b";B;N;9600;" in station.build_sourcetable(public=False)


def test_reference_identity_and_negative_ecef_coordinates(station: Station) -> None:
    for longitude in (8, -70, 170):
        located = replace(station, longitude=longitude)
        assert located.validate_frame(coordinate_frame(located))
    with pytest.raises(ValueError, match="2 cm"):
        station.validate_frame(coordinate_frame(station, delta=0.1))
    with pytest.raises(ValueError, match="station ID"):
        station.validate_frame(observation_frame(replace(station, station_id=43)))


def test_crc_failure_never_becomes_a_broadcast_frame(station: Station) -> None:
    raw = bytearray(observation_frame(station).raw)
    raw[-1] ^= 1
    decoder = StreamDecoder()
    assert not any(isinstance(value, RtcmMessage) for value in decoder.feed(bytes(raw)))


@pytest.mark.parametrize(
    "raw",
    [
        b"POST /TEST HTTP/1.1\r\n\r\n",
        b"SOURCE secret /TEST\r\n\r\n",
        b"GET /../TEST HTTP/1.1\r\n\r\n",
        b"GET /%54EST HTTP/1.1\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nAuthorization: a\r\nauthorization: b\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nContent-Length: 1\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nExpect: 100-continue\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\n User-Agent: folded\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nX: \x00\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nX: " + b"x" * 8192 + b"\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nHost: \r\n\r\n",
        b"GET /TEST HTTP/1.1\r\nHost: localhost\r\nX: \xff\r\n\r\n",
    ],
)
def test_request_smuggling_and_uploads_are_rejected(raw: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_request(raw)


def test_scrypt_credentials_and_file_permissions(tmp_path: Path) -> None:
    encoded = hash_password(ACCESS)
    credentials = Credentials({"rover": encoded})
    assert (
        credentials.verify(authorization().decode().strip().split(": ", 1)[1])
        == "rover"
    )
    assert credentials.verify("Basic !!!!") is None
    assert credentials.verify("Bearer abc") is None
    assert credentials.verify(authorization("unknown").decode().strip()[15:]) is None
    wrong = base64.b64encode(b"rover:a different long test credential").decode()
    assert credentials.verify("Basic " + wrong) is None
    with pytest.raises(ValueError):
        Credentials({"rover": "scrypt$bad$bad"})
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"rover": encoded}))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        Credentials.load(path)
    path.chmod(0o600)
    assert Credentials.load(path).verify("Basic " + wrong) is None


def test_public_v1_and_v2_streams_preserve_exact_rtcm(station: Station) -> None:
    async def scenario() -> None:
        async with running(station) as (caster, port):
            for version_two in (False, True):
                reader, writer, header = await request(
                    port, b"/TEST01", version_two=version_two
                )
                assert header.startswith(b"HTTP/1.1 200" if version_two else b"ICY 200")
                if not version_two:
                    assert header == b"ICY 200 OK\r\n"
                expected = coordinate_frame(station).raw
                received = (
                    await chunk(reader)
                    if version_two
                    else await reader.readexactly(len(expected))
                )
                assert received == expected
                caster.hub.publish(observation_frame(station))
                expected = observation_frame(station).raw
                received = (
                    await chunk(reader)
                    if version_two
                    else await reader.readexactly(len(expected))
                )
                assert received == expected
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())


def test_authentication_never_falls_back_to_guest(station: Station) -> None:
    async def scenario() -> None:
        async with running(
            station, public=False, users={"rover": hash_password(ACCESS)}
        ) as (_, port):
            reader, writer, header = await request(port, b"/TEST01")
            assert b"401 Unauthorized" in header
            assert b"WWW-Authenticate: Basic" in header
            writer.close()
            reader, writer, header = await request(port, b"/TEST01", authorization())
            assert b"200 OK" in header
            await chunk(reader)
            writer.close()
        async with running(station) as (_, port):
            _, writer, header = await request(
                port, b"/TEST01", b"Authorization: Basic !!!!\r\n"
            )
            assert b"401 Unauthorized" in header
            writer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize(
    ("user", "credential", "anonymous"),
    [
        ("", "", True),
        ("", ACCESS, False),
        ("rover", "", False),
        ("anon", ACCESS, False),
    ],
)
def test_only_an_empty_basic_pair_is_anonymous_on_a_public_stream(
    station: Station, public: bool, user: str, credential: str, anonymous: bool
) -> None:
    async def scenario() -> None:
        async with running(station, public=public) as (_, port):
            reader, writer, header = await request(
                port, b"/TEST01", authorization(user, credential)
            )
            if public and anonymous:
                assert b"200 OK" in header
                assert await chunk(reader) == coordinate_frame(station).raw
            else:
                assert b"401 Unauthorized" in header
            writer.close()
            await writer.wait_closed()

    asyncio.run(scenario())


def test_sourcetable_missing_mount_and_source_outage(station: Station) -> None:
    async def scenario() -> None:
        async with running(station) as (caster, port):
            reader, writer, header = await request(port, b"/", version_two=False)
            assert header.startswith(b"SOURCETABLE 200 OK")
            assert await reader.read() == station.build_sourcetable(public=True)
            writer.close()
            _, writer, header = await request(port, b"/missing")
            assert b"404 Not Found" in header
            writer.close()
            reader, writer, _ = await request(port, b"/TEST01")
            await chunk(reader)
            caster.hub.invalidate()
            assert await asyncio.wait_for(reader.read(), 1) == b""
            writer.close()
            _, writer, header = await request(port, b"/TEST01")
            assert b"503 Service Unavailable" in header
            writer.close()

    asyncio.run(scenario())


def test_slow_consumer_does_not_block_another_consumer(station: Station) -> None:
    hub = ready_hub(station, Limits(queue_frames=1))
    slow, fast = MagicMock(), MagicMock()
    slow_queue: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue(1)
    fast_queue: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue(1)
    hub.clients[slow], hub.clients[fast] = slow_queue, fast_queue
    message = observation_frame(station)
    hub.publish(message)
    assert fast_queue.get_nowait()[1] == message.raw
    hub.publish(message)
    slow.transport.abort.assert_called_once()
    fast.transport.abort.assert_not_called()
    assert fast_queue.get_nowait()[1] == message.raw
    assert hub.slow_clients == 1


def test_simultaneous_consumers_receive_identical_frames(station: Station) -> None:
    async def scenario() -> None:
        limits = Limits(connections=64, per_ip=64)
        async with running(station, limits=limits) as (caster, port):
            clients = await asyncio.gather(
                *(request(port, b"/TEST01") for _ in range(64))
            )
            assert all(b"200 OK" in header for _, _, header in clients)
            positions = await asyncio.gather(
                *(chunk(reader) for reader, _, _ in clients)
            )
            assert positions == [coordinate_frame(station).raw] * 64
            for _ in range(10):
                caster.hub.publish(observation_frame(station))
                observations = await asyncio.gather(
                    *(chunk(reader) for reader, _, _ in clients)
                )
                assert observations == [observation_frame(station).raw] * 64
            assert caster.hub.slow_clients == 0
            for _, writer, _ in clients:
                writer.close()
            await asyncio.gather(*(writer.wait_closed() for _, writer, _ in clients))

    asyncio.run(scenario())


def test_stale_coordinates_and_observations_disable_the_station(
    station: Station,
) -> None:
    hub = ready_hub(station)
    hub.last_observation = monotonic() - 11
    assert not hub.is_ready
    hub.publish(observation_frame(station))
    assert hub.is_ready
    hub.coordinate = (monotonic() - 31, coordinate_frame(station).raw)
    assert not hub.is_ready


def test_header_timeout_releases_connection_capacity(station: Station) -> None:
    async def scenario() -> None:
        limits = Limits(connections=1, per_ip=1, header_seconds=0.05)
        async with running(station, limits=limits) as (caster, port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /")
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 1) == b""
            writer.close()
            await writer.wait_closed()
            _, writer, header = await request(port, b"/healthz")
            assert b"200 OK" in header
            writer.close()
        assert not caster.tasks
        assert not caster.peers

    asyncio.run(scenario())


def test_per_user_connection_limit(station: Station) -> None:
    async def scenario() -> None:
        async with running(
            station,
            public=False,
            limits=Limits(per_user=1),
            users={"rover": hash_password(ACCESS)},
        ) as (_, port):
            reader, first, _ = await request(port, b"/TEST01", authorization())
            await chunk(reader)
            _, second, header = await request(port, b"/TEST01", authorization())
            assert b"429 Too Many Requests" in header
            first.close()
            second.close()

    asyncio.run(scenario())


def test_external_plaintext_listener_is_rejected() -> None:
    args = argparse.Namespace(bind="192.0.2.1", tls_cert=None, tls_key=None)
    with pytest.raises(ValueError, match="require a TLS"):
        create_tls_context(args)
    args.bind = "127.0.0.1"
    assert create_tls_context(args) is None
    args.bind = "::1"
    assert create_tls_context(args) is None


@pytest.fixture
def tls_files(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("TLS integration requires openssl")
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        capture_output=True,
        check=True,
    )
    yield cert, key


def test_verified_tls_relay_checks_station_before_fanout(
    station: Station, tls_files: tuple[Path, Path]
) -> None:
    async def scenario() -> None:
        cert, key = tls_files
        context = create_tls_context(
            argparse.Namespace(bind="127.0.0.1", tls_cert=cert, tls_key=key)
        )
        async with running(
            station,
            public=False,
            users={"edge": hash_password(ACCESS)},
            context=context,
        ) as (origin, port):
            edge = Hub(station, Limits())
            upstream = Upstream(
                "localhost",
                port,
                "edge",
                ACCESS,
                ssl.create_default_context(cafile=cert),
            )
            relay = asyncio.create_task(read_upstream(edge, upstream))
            try:
                async with asyncio.timeout(3):
                    while not edge.is_ready:
                        origin.hub.publish(observation_frame(station))
                        await asyncio.sleep(0.01)
                assert edge.coordinate is not None
                assert edge.coordinate[1] == coordinate_frame(station).raw
            finally:
                relay.cancel()
                await asyncio.gather(relay, return_exceptions=True)

    asyncio.run(scenario())


def test_fatal_coordinate_error_invalidates_existing_streams(station: Station) -> None:
    async def scenario() -> None:
        hub = ready_hub(station)
        writer = MagicMock()
        hub.clients[writer] = asyncio.Queue(1)

        async def bad_source() -> None:
            hub.publish(coordinate_frame(station, delta=1))

        with pytest.raises(ValueError, match="2 cm"):
            await supervise(hub, bad_source)
        writer.transport.abort.assert_called_once()
        assert not hub.is_ready

    asyncio.run(scenario())


def test_serial_source_initializes_through_the_library_and_closes_on_failure(
    station: Station, monkeypatch: pytest.MonkeyPatch
) -> None:
    receiver = MagicMock()
    receiver.__aenter__ = AsyncMock(return_value=receiver)
    receiver.__aexit__ = AsyncMock(return_value=None)
    receiver.execute = AsyncMock()
    receiver.receive = AsyncMock(
        side_effect=[
            ResponseTimeout("quiet after UNLOG"),
            coordinate_frame(station),
            observation_frame(station),
            OSError("synthetic disconnection"),
        ]
    )
    connection = AsyncMock(return_value=receiver)
    monkeypatch.setattr(
        "examples.ntrip_server.source.AsyncReceiver.connect", connection
    )
    hub = Hub(station, Limits())
    with pytest.raises(OSError, match="synthetic disconnection"):
        asyncio.run(read_receiver(hub, "synthetic-port", 921600, timeout=2))
    connection.assert_awaited_once_with("synthetic-port", 921600, timeout=2)
    commands = [call.args[0].text for call in receiver.execute.await_args_list]
    assert commands == [
        "UNLOG",
        *(command.text for command in station.build_commands()),
    ]
    assert hub.is_ready
    receiver.__aexit__.assert_awaited_once()


def test_rinex_uses_library_multifrequency_export_and_measured_offsets() -> None:
    records = [record(0, [observation(), observation(signal=9, frequency=1227.60e6)])]
    metadata = {
        "marker_name": "TEST01",
        "antenna_type": "TEST-ANTENNA   NONE",
        "antenna_serial": "ANT123",
        "receiver_serial": "RX123",
        "receiver_firmware": "test-build",
        "approx_position": ecef_from_geodetic(50, 8, 100),
        "antenna_hen": (1.2345, 0.001, -0.002),
    }
    text = export_survey(records, **metadata)
    lines = text.splitlines()
    assert any("C1C" in line and "L2W" in line for line in lines)
    offsets = next(line for line in lines if line[60:] == "ANTENNA: DELTA H/E/N")
    assert offsets[:42] == f"{1.2345:14.4f}{0.001:14.4f}{-0.002:14.4f}"
    assert next(line for line in lines if line[60:] == "ANT # / TYPE").startswith(
        "ANT123"
    )
    assert "not calibrated" not in text
    with pytest.raises(ValueError, match="dual-frequency"):
        export_survey([record(0, [observation()])], **metadata)
    with pytest.raises(ValueError, match="dual-frequency"):
        export_survey(
            [record(0, [observation(), observation(signal=6, frequency=1176.45e6)])],
            **metadata,
        )


def test_bad_survey_metadata_is_rejected_before_opening_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examples.ntrip_server.__main__ import _build_parser

    args = _build_parser().parse_args(
        [
            "--survey-output",
            str(tmp_path / "base.rnx"),
            "--antenna-type",
            "x" * 21,
            "--antenna-serial",
            "test",
            "--receiver-serial",
            "test",
            "--receiver-firmware",
            "test",
            "--approx-position",
            "4060000",
            "571000",
            "4880000",
            "--antenna-hen",
            "0",
            "0",
            "0",
        ]
    )
    capture = MagicMock(side_effect=AssertionError("opened a receiver"))
    monkeypatch.setattr("examples.ntrip_server.survey.capture_records", capture)
    with pytest.raises(ValueError, match=r"1\.\.20"):
        capture_survey(args)
    capture.assert_not_called()
    assert not args.survey_output.exists()
