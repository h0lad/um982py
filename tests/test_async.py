import asyncio
from threading import Event
from unittest.mock import patch

import pytest

from conftest import ReplayTransport
from um982py import AsyncReceiver, Receiver
from um982py.errors import ResponseTimeout


def test_async_factories() -> None:
    async def run() -> None:
        for method in ("serial", "tcp"):
            transport = ReplayTransport()
            with patch.object(Receiver, method, return_value=Receiver(transport)):
                receiver = await getattr(AsyncReceiver, method)("port", 123)
                await receiver.close()
            assert transport.closed

    asyncio.run(run())


def test_async_target_selection() -> None:
    async def run() -> None:
        transport = ReplayTransport()
        with patch.object(
            Receiver, "connect", return_value=Receiver(transport)
        ) as factory:
            receiver = await AsyncReceiver.connect("tcp://127.0.0.1:4001", 921600)
            await receiver.close()
        factory.assert_called_once_with("tcp://127.0.0.1:4001", 921600, timeout=3)
        assert transport.closed

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_repeated_cancellation_preserves_lock(failure: bool) -> None:
    async def run() -> None:
        started, release, finished = Event(), Event(), Event()
        receiver = AsyncReceiver(Receiver(ReplayTransport()))

        def operation() -> str:
            started.set()
            assert release.wait(2)
            finished.set()
            if failure:
                raise ResponseTimeout("late timeout")
            return "done"

        task = asyncio.create_task(receiver._run(operation))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        next_task = asyncio.create_task(receiver._run(lambda: "next"))
        await asyncio.sleep(0.01)
        assert not next_task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and await next_task == "next"

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_cancelled_open_cleans_up(failure: bool) -> None:
    async def run() -> None:
        started, release = Event(), Event()
        transport = ReplayTransport()

        def operation() -> Receiver:
            started.set()
            assert release.wait(2)
            if failure:
                raise OSError("open failed")
            return Receiver(transport)

        task = asyncio.create_task(AsyncReceiver._connect(operation))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.closed is not failure

    asyncio.run(run())


def test_async_drain_pending_returns_queued_messages() -> None:
    from conftest import acknowledgement, sentence
    from um982py.commands.core import action

    async def run() -> None:
        raw = sentence(b"GPGGA,1")
        transport = ReplayTransport({b"RESET\r\n": raw + acknowledgement("RESET")})
        async with AsyncReceiver(Receiver(transport)) as receiver:
            await receiver.execute(action("RESET"))
            assert [message.raw for message in await receiver.drain_pending()] == [raw]
            assert await receiver.drain_pending() == ()

    asyncio.run(run())
