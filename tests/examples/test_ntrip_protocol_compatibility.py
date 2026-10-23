"""Check NTRIP v1 replies and HTTP chunk framing for the relay."""

import asyncio
from dataclasses import replace

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.source import _relay_body

from tests.examples.test_ntrip_server import (
    observation_frame,
    ready_hub,
    request,
    running,
)
from tests.examples.test_ntrip_server import station as station


def test_v1_sourcetable_and_unknown_mountpoint(station: Station) -> None:
    async def scenario() -> None:
        async with running(station) as (_, port):
            for path in (b"/", b"/missing"):
                reader, writer, header = await request(port, path, version_two=False)
                assert header.startswith(b"SOURCETABLE 200 OK\r\n")
                assert b"Content-Type: text/plain\r\n" in header
                assert b"Server: um982py/NtripV2.0\r\n" in header
                assert await reader.read() == station.build_sourcetable(public=True)
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())


def test_sourcetable_uses_operator_stream_metadata(station: Station) -> None:
    fields = (
        replace(station, carrier=1, bitrate=2400)
        .build_sourcetable(public=True)
        .splitlines()[0]
        .decode()
        .split(";")
    )
    assert fields[5] == "1"
    assert fields[17] == "2400"
    with pytest.raises(ValueError, match="carrier"):
        replace(station, carrier=3)
    with pytest.raises(ValueError, match="bitrate"):
        replace(station, bitrate=-1)


def test_upstream_handles_large_chunks_extensions_and_trailers(
    station: Station,
) -> None:
    async def scenario() -> None:
        hub = ready_hub(station)
        message = observation_frame(station).raw
        body = message * 3500
        reader = asyncio.StreamReader()
        reader.feed_data(
            f"{len(body):X}".encode()
            + b';extension="quoted value";flag\r\n'
            + body
            + b"\r\n0;done=yes\r\nExample: value\r\n\r\n"
        )
        reader.feed_eof()
        before = hub.frames
        with pytest.raises(OSError, match="upstream ended"):
            await _relay_body(reader, hub, True)
        assert hub.frames - before == 3500

    asyncio.run(scenario())
