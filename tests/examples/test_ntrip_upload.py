"""Check isolated source upload access and BKG source interoperability."""

import asyncio
import base64
import os
import shutil
import signal

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, Hub, Limits, listen

from tests.examples.test_ntrip_server import (
    coordinate_frame,
    observation_frame,
    request,
)
from tests.examples.test_ntrip_server import station as station

ACCESS = "synthetic-upload-password"


@pytest.mark.parametrize("version", (1, 2))
def test_bkg_source_uploads_to_rover(station: Station, version: int) -> None:
    configured = os.environ.get("NTRIP_BKG_SERVER")
    if configured is None:
        pytest.skip("set NTRIP_BKG_SERVER to BKG ntripserver")
    executable = shutil.which(configured)
    if executable is None:
        pytest.fail(f"BKG ntripserver does not exist: {configured}")

    async def scenario() -> None:
        hub = Hub(station, Limits())
        source_users = Credentials({"source": hash_password(ACCESS)})
        caster = Caster(
            hub, Credentials({}), public=True, source_credentials=source_users
        )
        destination = await listen(caster, "127.0.0.1", 0, None)
        dest_port = destination.sockets[0].getsockname()[1]
        writers: set[asyncio.StreamWriter] = set()

        async def feed(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writers.add(writer)
            try:
                while True:
                    writer.write(
                        coordinate_frame(station).raw + observation_frame(station).raw
                    )
                    await writer.drain()
                    await asyncio.sleep(0.2)
            except (OSError, ConnectionError):
                pass
            finally:
                writers.discard(writer)
                writer.close()

        upstream = await asyncio.start_server(feed, "127.0.0.1", 0)
        source_port = upstream.sockets[0].getsockname()[1]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "-M",
                "2",
                "-H",
                "127.0.0.1",
                "-P",
                str(source_port),
                "-O",
                "3" if version == 1 else "1",
                "-a",
                "127.0.0.1",
                "-p",
                str(dest_port),
                "-m",
                station.mountpoint,
                "-n",
                "source",
                "-c",
                ACCESS,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            async with asyncio.timeout(8):
                while not hub.is_ready:
                    if process.returncode is not None:
                        error = await process.stderr.read()
                        pytest.fail(
                            f"BKG source exited: {error.decode(errors='replace')}"
                        )
                    await asyncio.sleep(0.05)
            reader, writer, header = await request(
                dest_port, b"/TEST01", version_two=False
            )
            assert header == b"ICY 200 OK\r\n"
            assert (
                await asyncio.wait_for(
                    reader.readexactly(len(coordinate_frame(station).raw)), 2
                )
                == coordinate_frame(station).raw
            )
            writer.close()
            await writer.wait_closed()
            assert hub.frames >= 2
            duplicate_reader, duplicate_writer = await asyncio.open_connection(
                "127.0.0.1", dest_port
            )
            token = base64.b64encode(f"source:{ACCESS}".encode())
            duplicate_writer.write(
                b"POST /TEST01 HTTP/1.1\r\nHost: localhost\r\n"
                b"Ntrip-Version: Ntrip/2.0\r\nTransfer-Encoding: chunked\r\n"
                b"Authorization: Basic " + token + b"\r\n\r\n"
            )
            await duplicate_writer.drain()
            assert b"409 Conflict" in await duplicate_reader.read()
            duplicate_writer.close()
            await duplicate_writer.wait_closed()
            process.send_signal(signal.SIGINT)
            await asyncio.wait_for(process.wait(), 3)
            async with asyncio.timeout(3):
                while caster.source_active:
                    await asyncio.sleep(0.05)
            assert not hub.is_ready
        finally:
            if process is not None and process.returncode is None:
                process.send_signal(signal.SIGINT)
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            for writer in tuple(writers):
                writer.close()
            upstream.close()
            await upstream.wait_closed()
            destination.close()
            await destination.wait_closed()
            await caster.close()

    asyncio.run(scenario())


def test_source_credentials_are_separate_from_rover_accounts(station: Station) -> None:
    async def scenario() -> None:
        hub = Hub(station, Limits())
        caster = Caster(
            hub,
            Credentials({"rover": hash_password(ACCESS)}),
            public=True,
            source_credentials=Credentials({"source": hash_password(ACCESS)}),
        )
        server = await listen(caster, "127.0.0.1", 0, None)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            token = base64.b64encode(f"rover:{ACCESS}".encode())
            writer.write(
                b"POST /TEST01 HTTP/1.1\r\nHost: localhost\r\n"
                b"Ntrip-Version: Ntrip/2.0\r\nTransfer-Encoding: chunked\r\n"
                b"Authorization: Basic " + token + b"\r\n\r\n"
            )
            await writer.drain()
            assert b"401 Unauthorized" in await reader.read()
            assert not hub.is_ready
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            await caster.close()

    asyncio.run(scenario())
