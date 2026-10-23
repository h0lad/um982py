"""Exercise the caster with the independently supplied BKG BNC client."""

import asyncio
import os
import shutil
import signal
from pathlib import Path

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.auth import Credentials
from examples.ntrip_server.caster import Caster, listen

from tests.examples.test_ntrip_server import (
    coordinate_frame,
    observation_frame,
    ready_hub,
)
from tests.examples.test_ntrip_server import station as station
from um982py.messages import RtcmMessage
from um982py.protocol import StreamDecoder


@pytest.mark.parametrize("version", (1, 2))
def test_bnc_receives_rtcm(station: Station, tmp_path: Path, version: int) -> None:
    configured = os.environ.get("NTRIP_BNC")
    if configured is None:
        pytest.skip("set NTRIP_BNC to the BKG BNC executable")
    executable = shutil.which(configured)
    if executable is None:
        pytest.fail(f"BNC executable does not exist: {configured}")

    async def scenario() -> None:
        hub = ready_hub(station)
        caster = Caster(hub, Credentials({}), public=True)
        server = await listen(caster, "127.0.0.1", 0, None)
        port = server.sockets[0].getsockname()[1]
        config = tmp_path / "bnc.bnc"
        config.write_text(
            "[General]\n"
            "autoStart=2\n"
            f"mountPoints=//127.0.0.1:{port}/{station.mountpoint} "
            f"RTCM_3.2 DEU 50 8 no {version}\n"
            f"ntripVersion={version}\n"
            f"rawOutFile={tmp_path / 'received.raw'}\n"
            f"logFile={tmp_path / 'bnc.log'}\n"
        )

        async def feed() -> None:
            while True:
                hub.publish(coordinate_frame(station))
                hub.publish(observation_frame(station))
                await asyncio.sleep(0.2)

        producer = asyncio.create_task(feed())
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "--nw",
                "--conf",
                str(config),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(3)
            if process.returncode is None:
                process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await process.wait()
            assert process.returncode == 0
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            server.close()
            await server.wait_closed()
            await caster.close()

        captures = list(tmp_path.glob("received.raw_*"))
        assert len(captures) == 1
        decoder = StreamDecoder(strict=True)
        messages = []
        with captures[0].open("rb") as capture:
            assert capture.readline().startswith(b"1 Version of BNC raw file")
            while line := capture.readline():
                if line.strip():
                    size = int(line.split()[-1])
                    data = capture.read(size)
                    assert len(data) == size
                    messages.extend(decoder.feed(data))
        assert {m.message_type for m in messages if isinstance(m, RtcmMessage)} == {
            1005,
            1074,
        }
        assert not decoder.pending

    asyncio.run(scenario())
