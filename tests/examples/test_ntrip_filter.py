"""Check sourcetable filters with BKG's independent NTRIP client."""

import asyncio
import os
import shutil

import pytest
from examples.ntrip_server import Station
from examples.ntrip_server.filtering import filter_table

from tests.examples.test_ntrip_server import running
from tests.examples.test_ntrip_server import station as station


@pytest.mark.parametrize(
    ("query", "found"),
    [
        ("STR;TEST*", True),
        ("STR;OTHER*", False),
        ("STR;;;;;;;;DEU", True),
        ("STR;;;;;;;;FRA", False),
        ("STR;TEST*&!(OTHER)", True),
        ("STR;;;;;;;;;>=49&<51", True),
        ("STR;;;;;;;;;>60", False),
    ],
)
def test_filter_single_station(station: Station, query: str, found: bool) -> None:
    table = filter_table(station.build_sourcetable(public=True), query)
    assert (b"STR;TEST01;" in table) is found
    assert table.endswith(b"ENDSOURCETABLE\r\n")


@pytest.mark.parametrize(
    ("query", "found"), [("?STR;TEST*", True), ("?STR;OTHER*", False)]
)
def test_bkg_client_requests_filtered_table(
    station: Station, query: str, found: bool
) -> None:
    configured = os.environ.get("NTRIP_BKG_CLIENT")
    if configured is None:
        pytest.skip("set NTRIP_BKG_CLIENT to BKG ntripclient")
    executable = shutil.which(configured)
    if executable is None:
        pytest.fail(f"BKG ntripclient does not exist: {configured}")

    async def scenario() -> None:
        async with running(station) as (_, port):
            process = await asyncio.create_subprocess_exec(
                executable,
                "-s",
                "127.0.0.1",
                "-r",
                str(port),
                "-M",
                "http",
                "-m",
                query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                output, error = await asyncio.wait_for(process.communicate(), 5)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert b"ENDSOURCETABLE" in output, error.decode(errors="replace")
            assert (b"STR;TEST01;" in output) is found

    asyncio.run(scenario())
