"""Exercise the short receiver workflows with recorded messages."""

import asyncio
from pathlib import Path
from threading import Event

import pytest

from conftest import ReplayTransport, sentence
from um982py import AsyncReceiver, Receiver


def test_positions_poll_until_the_caller_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = sentence(b"GNGGA,145842.00,5232.0000,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,")
    transport = ReplayTransport({b"GPGGA\r\n": raw})
    waits: list[float] = []
    monkeypatch.setattr("um982py.receiver.sleep", waits.append)
    with Receiver(transport) as receiver:
        positions = receiver.positions(interval=2)
        assert next(positions).latitude == pytest.approx(52.5333333333)
        assert next(positions).longitude == pytest.approx(13.3666666667)
        positions.close()
        assert waits == [2]
        assert not transport.closed
    assert transport.writes == [b"GPGGA\r\n", b"GPGGA\r\n"]
    assert transport.closed


def test_positions_stop_event_ends_polling() -> None:
    raw = sentence(b"GNGGA,145842.00,5232.0000,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,")
    transport = ReplayTransport({b"GPGGA\r\n": raw})
    stop = Event()
    with Receiver(transport) as receiver:
        positions = receiver.positions(interval=60, stop=stop)
        assert next(positions).valid
        stop.set()
        with pytest.raises(StopIteration):
            next(positions)
    assert transport.writes == [b"GPGGA\r\n"]


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf"), True])
def test_positions_reject_invalid_intervals_before_querying(interval: float) -> None:
    transport = ReplayTransport()
    with Receiver(transport) as receiver, pytest.raises(ValueError, match="interval"):
        receiver.positions(interval=interval)
    assert not transport.writes


def test_async_positions_and_satellites() -> None:
    async def run() -> None:
        raw = sentence(
            b"GNGGA,145842.00,5232.0000,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,"
        )
        sat = (Path(__file__).parent / "fixtures/bodies/SATSINFOB.bin").read_bytes()
        transport = ReplayTransport({b"GPGGA\r\n": raw, b"SATSINFOB\r\n": sat})
        async with AsyncReceiver(Receiver(transport)) as receiver:
            positions = receiver.positions(interval=0.001)
            first = await anext(positions)
            second = await anext(positions)
            await positions.aclose()
            assert first.valid and second.valid
            satellites = await receiver.satellites()
            assert satellites[0].constellation == "GPS"
            assert satellites[0].signals[0].name == "L1 C/A"
            stop = asyncio.Event()
            stopped = receiver.positions(interval=60, stop=stop)
            assert (await anext(stopped)).valid
            stop.set()
            with pytest.raises(StopAsyncIteration):
                await anext(stopped)
        assert transport.closed

    asyncio.run(run())
