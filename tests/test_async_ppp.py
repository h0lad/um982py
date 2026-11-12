"""Exercise asynchronous PPP setup, polling and cancellation."""

import asyncio
from threading import Event

import pytest

from test_ppp_easy import Config, FakeReceiver, _receiver
from um982py import AsyncReceiver
from um982py.commands.configuration import SignalGroup
from um982py.errors import CommandRejected
from um982py.ppp import PppService, PppSession, _start_ppp


class PppReceiver(FakeReceiver):
    def start_ppp(self, *, service: PppService = "E6-HAS") -> PppSession:
        return _start_ppp(_receiver(self), service=service)


@pytest.mark.parametrize("service", ["B2B-PPP", "L6MDCPPP"])
def test_async_ppp_setup_and_positions(service: PppService) -> None:
    async def run() -> None:
        receiver = PppReceiver(Config(SignalGroup(4, 5), False, None))
        session = await AsyncReceiver(_receiver(receiver)).start_ppp(service=service)
        assert session.service == service
        assert receiver.commands == [
            "CONFIG SIGNALGROUP 3 6",
            f"CONFIG PPP ENABLE {service}",
        ]
        assert session.previous_group == SignalGroup(4, 5)
        assert session.active_group == SignalGroup(3, 6)
        assert session.previous_enabled is False and session.previous_service is None
        assert session.group_changed and session.service_changed
        assert (await session.position()).valid

        stop = asyncio.Event()
        positions = session.positions(interval=30, stop=stop)
        assert (await anext(positions)).valid
        waiting = asyncio.create_task(anext(positions))
        await asyncio.sleep(0)
        stop.set()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(waiting, timeout=1)
        assert receiver.reads == 2
        with pytest.raises(ValueError, match="interval"):
            await anext(session.positions(interval=0))

    asyncio.run(run())


def test_async_setup_reports_rejection_and_partial_changes() -> None:
    async def run() -> None:
        receiver = PppReceiver(Config(SignalGroup(4, 5), False, None))
        receiver.fail = "CONFIG PPP ENABLE E6-HAS"
        with pytest.raises(CommandRejected) as caught:
            await AsyncReceiver(_receiver(receiver)).start_ppp()
        assert receiver.config.signal_group == SignalGroup(3, 6)
        assert any(
            "settings may have changed" in note for note in caught.value.__notes__
        )

    asyncio.run(run())


def test_async_position_iteration_can_be_cancelled() -> None:
    async def run() -> None:
        receiver = PppReceiver(Config(SignalGroup(3, 6), True, "E6-HAS"))
        session = await AsyncReceiver(_receiver(receiver)).start_ppp()
        positions = session.positions(interval=30)
        assert (await anext(positions)).valid
        pending = asyncio.create_task(anext(positions))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(StopAsyncIteration):
            await anext(positions)
        assert receiver.reads == 1

    asyncio.run(run())


def test_cancelled_async_setup_waits_for_the_receiver_and_preserves_lock() -> None:
    async def run() -> None:
        started, release, finished = Event(), Event(), Event()

        class SlowReceiver(PppReceiver):
            def start_ppp(self, *, service: PppService = "E6-HAS") -> PppSession:
                started.set()
                assert release.wait(2)
                session = super().start_ppp(service=service)
                finished.set()
                return session

        receiver = SlowReceiver(Config(SignalGroup(4, 5), False, None))
        asynchronous = AsyncReceiver(_receiver(receiver))
        task = asyncio.create_task(asynchronous.start_ppp())
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        following = asyncio.create_task(asynchronous._run(lambda: "next"))
        await asyncio.sleep(0.01)
        assert not following.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert finished.is_set()
        assert any("may have changed" in note for note in caught.value.__notes__)
        assert await following == "next"

    asyncio.run(run())
