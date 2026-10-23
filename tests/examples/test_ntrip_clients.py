"""Checks interoperability with unmodified third-party NTRIP clients."""

import asyncio
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, listen

from tests.examples.test_ntrip_server import (
    ACCESS,
    coordinate_frame,
    frame,
    ready_hub,
)
from tests.examples.test_ntrip_server import station as station
from tests.examples.test_ntrip_server import tls_files as tls_files
from um982py.messages import RtcmMessage
from um982py.protocol import StreamDecoder

CLIENTS = (
    pytest.param("str2str", "1.0", False, id="rtklib-v1"),
    pytest.param("bkg", "1.0", False, id="bkg-v1"),
    pytest.param("bkg", "2.0", False, id="bkg-v2"),
    pytest.param("pygnss", "1.0", False, id="pygnss-v1"),
    pytest.param("pygnss", "2.0", False, id="pygnss-v2"),
    pytest.param("pygnss", "1.0", True, id="pygnss-v1-tls"),
    pytest.param("pygnss", "2.0", True, id="pygnss-v2-tls"),
)
ENVIRONMENT = {
    "str2str": "NTRIP_STR2STR",
    "bkg": "NTRIP_BKG_CLIENT",
    "pygnss": "NTRIP_PYGNSS_CLIENT",
}


@dataclass(frozen=True, slots=True)
class ClientResult:
    """The actual client output and server-side authentication decisions."""

    raw: bytes
    stderr: str
    denied: int


class ProbeCaster(Caster):
    """Count denied requests without changing the server's authorization decisions."""

    denied = 0

    async def _authorize(self, authorization: str | None) -> str | None:
        user = await super()._authorize(authorization)
        if user is None:
            self.denied += 1
        return user


def client_executable(name: str) -> str:
    configured = os.environ.get(ENVIRONMENT[name])
    if configured is None:
        pytest.skip(f"set {ENVIRONMENT[name]} to run the downloaded client")
    executable = shutil.which(configured)
    if executable is None:
        pytest.fail(f"client executable does not exist: {configured}")
    return executable


@pytest.fixture(autouse=True)
def require_downloaded_client(request: pytest.FixtureRequest) -> None:
    client_executable(str(request.node.callspec.params["name"]))


def client_command(
    executable: str,
    name: str,
    version: str,
    port: int,
    output: Path,
    *,
    username: str,
    credential: str,
    mountpoint: str,
    certificate: Path | None,
) -> list[str]:
    if name == "str2str":
        account = f"{username}:{credential}@" if username else ""
        return [
            executable,
            "-in",
            f"ntrip://{account}127.0.0.1:{port}/{mountpoint}",
            "-out",
            str(output),
        ]
    if name == "bkg":
        command = [
            executable,
            "-s",
            "127.0.0.1",
            "-r",
            str(port),
            "-M",
            "ntrip1" if version == "1.0" else "http",
        ]
        if mountpoint:
            command += ["-m", mountpoint]
        if username:
            command += ["-u", username, "-p", credential]
        return command
    command = [
        executable,
        "-S",
        "localhost",
        "-P",
        str(port),
        "-M",
        mountpoint,
        "--ntripversion",
        version,
        "--ntripuser",
        username,
        "--ntrippassword",
        credential,
        "--retries",
        "0",
        "--timeout",
        "2",
        "--clioutput",
        "1",
        "--output",
        str(output),
        "--verbosity",
        "1",
    ]
    if certificate is not None:
        command += ["--https", "1", "--selfsign", "1", "--tlscrtpath", str(certificate)]
    return command


async def run_client(
    station: Station,
    command_name: str,
    version: str,
    tmp_path: Path,
    *,
    public: bool,
    invalid: bool = False,
    table: bool = False,
    tls: tuple[Path, Path] | None = None,
) -> ClientResult:
    import ssl

    executable = client_executable(command_name)
    context = None
    if tls is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(*tls)
    hub = ready_hub(station)
    caster = ProbeCaster(
        hub, Credentials({"rover": hash_password(ACCESS)}), public=public
    )
    frames = (
        coordinate_frame(station),
        *(
            frame(((kind << 12) | station.station_id).to_bytes(3, "big") + bytes(19))
            for kind in (1074, 1094, 1124)
        ),
    )

    async def feed() -> None:
        while True:
            for message in frames:
                hub.publish(message)
            await asyncio.sleep(0.15)

    server = await listen(caster, "127.0.0.1", 0, context)
    producer = asyncio.create_task(feed())
    output = tmp_path / "received.rtcm"
    error_path = tmp_path / "client.stderr"
    process: asyncio.subprocess.Process | None = None
    try:
        port = server.sockets[0].getsockname()[1]
        command = client_command(
            executable,
            command_name,
            version,
            port,
            output,
            username="rover" if invalid or not public else "",
            credential="wrong synthetic credential"
            if invalid
            else ACCESS
            if not public
            else "",
            mountpoint="" if table else station.mountpoint,
            certificate=tls[0] if tls else None,
        )
        with output.open("wb") as stdout, error_path.open("wb") as stderr:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=stdout if command_name == "bkg" else asyncio.subprocess.DEVNULL,
                stderr=stderr,
                cwd=tmp_path,
            )
            await asyncio.sleep(1.5)
            if process.returncode is None:
                process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await process.wait()
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        server.close()
        await server.wait_closed()
        await caster.close()
    return ClientResult(
        output.read_bytes(), error_path.read_text(errors="replace"), caster.denied
    )


@pytest.mark.parametrize(("name", "version", "tls"), CLIENTS)
@pytest.mark.parametrize("public", [False, True], ids=("authenticated", "guest"))
def test_downloaded_client_receives_only_intact_rtcm(
    station: Station,
    tmp_path: Path,
    tls_files: tuple[Path, Path],
    name: str,
    version: str,
    tls: bool,
    public: bool,
) -> None:
    result = asyncio.run(
        run_client(
            station,
            name,
            version,
            tmp_path,
            public=public,
            tls=tls_files if tls else None,
        )
    )
    decoder = StreamDecoder(strict=True)
    messages = decoder.feed(result.raw)
    assert len(messages) >= 4, result.stderr
    assert all(isinstance(message, RtcmMessage) for message in messages)
    assert {m.message_type for m in messages if isinstance(m, RtcmMessage)} == {
        1005,
        1074,
        1094,
        1124,
    }, result.stderr
    assert b"".join(message.raw for message in messages) == result.raw
    assert not decoder.pending
    assert result.denied == 0


@pytest.mark.parametrize(("name", "version", "tls"), CLIENTS)
@pytest.mark.parametrize("public", [False, True], ids=("private", "public"))
def test_downloaded_client_with_invalid_credentials_gets_no_corrections(
    station: Station,
    tmp_path: Path,
    tls_files: tuple[Path, Path],
    name: str,
    version: str,
    tls: bool,
    public: bool,
) -> None:
    result = asyncio.run(
        run_client(
            station,
            name,
            version,
            tmp_path,
            public=public,
            invalid=True,
            tls=tls_files if tls else None,
        )
    )
    assert result.raw == b"", result.stderr
    assert result.denied > 0, result.stderr


@pytest.mark.parametrize(("name", "version", "tls"), CLIENTS[1:])
def test_downloaded_client_retrieves_the_sourcetable(
    station: Station,
    tmp_path: Path,
    tls_files: tuple[Path, Path],
    name: str,
    version: str,
    tls: bool,
) -> None:
    result = asyncio.run(
        run_client(
            station,
            name,
            version,
            tmp_path,
            public=False,
            table=True,
            tls=tls_files if tls else None,
        )
    )
    assert b"TEST01" in result.raw, result.stderr
    assert b"RTCM 3.2" in result.raw, result.stderr
