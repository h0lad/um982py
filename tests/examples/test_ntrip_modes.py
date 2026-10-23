"""Verify the private mode protects station discovery as well as streams."""

import asyncio
import base64
import json
import socket
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, Limits, listen

from tests.examples.test_ntrip_server import observation_frame, ready_hub, request
from tests.examples.test_ntrip_server import station as station

ACCESS = "synthetic-rover-credential"


def test_private_mode_protects_sourcetable_and_stream(station: Station) -> None:
    async def scenario() -> None:
        caster = Caster(
            ready_hub(station),
            Credentials({"rover": hash_password(ACCESS)}),
            protect_table=True,
        )
        server = await listen(caster, "127.0.0.1", 0, None)
        port = server.sockets[0].getsockname()[1]
        try:
            for path in (b"/", b"/TEST01"):
                reader, writer, header = await request(port, path)
                assert b"401 Unauthorized" in header
                assert b"TEST01" not in await reader.read()
                writer.close()
                await writer.wait_closed()
            token = base64.b64encode(f"rover:{ACCESS}".encode())
            headers = b"Authorization: Basic " + token + b"\r\n"
            reader, writer, header = await request(port, b"/", headers)
            assert b"200 OK" in header
            assert b"TEST01" in await reader.read()
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            await caster.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ("public", "private"))
def test_cli_mode_policy(station: Station, tmp_path: Path, mode: str) -> None:
    async def scenario() -> None:
        manifest = tmp_path / "station.json"
        manifest.write_text(json.dumps(asdict(station)))
        accounts = tmp_path / "users.json"
        accounts.write_text(json.dumps({"rover": hash_password(ACCESS)}))
        accounts.chmod(0o600)
        source_accounts = tmp_path / "source.json"
        source_accounts.write_text(json.dumps({"source": hash_password(ACCESS)}))
        source_accounts.chmod(0o600)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "examples.ntrip_server",
            "--mode",
            mode,
            "--station",
            str(manifest),
            "--users",
            str(accounts),
            "--source-users",
            str(source_accounts),
            "--listen-port",
            str(port),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(5):
                while True:
                    try:
                        reader, writer, header = await request(port, b"/")
                        break
                    except ConnectionRefusedError:
                        if process.returncode is not None:
                            output = await process.stderr.read()
                            pytest.fail(output.decode(errors="replace"))
                        await asyncio.sleep(0.05)
            body = await reader.read()
            assert (b"200 OK" in header) == (mode == "public")
            assert (b"STR;TEST01" in body) == (mode == "public")
            writer.close()
            await writer.wait_closed()
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), 3)

    asyncio.run(scenario())


def test_public_caster_fans_out_to_128_concurrent_clients(station: Station) -> None:
    async def scenario() -> None:
        hub = ready_hub(station, Limits(connections=150, per_ip=150))
        caster = Caster(hub, Credentials({}), public=True)
        server = await listen(caster, "127.0.0.1", 0, None)
        port = server.sockets[0].getsockname()[1]
        connections = []
        try:
            # Stay within the default 100 connections/second admission budget.
            for _ in range(8):
                for _ in range(16):
                    reader, writer, header = await request(
                        port, b"/TEST01", version_two=False
                    )
                    assert header == b"ICY 200 OK\r\n"
                    connections.append((reader, writer))
                await asyncio.sleep(0.2)
            assert len(hub.clients) == 128
            message = observation_frame(station).raw
            hub.publish(observation_frame(station))
            for reader, _ in connections:
                await asyncio.wait_for(reader.readexactly(25), 3)  # initial 1005
                assert (
                    await asyncio.wait_for(reader.readexactly(len(message)), 3)
                    == message
                )
        finally:
            for _, writer in connections:
                writer.close()
            server.close()
            await server.wait_closed()
            await caster.close()

    asyncio.run(scenario())
