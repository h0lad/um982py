"""Continuous polling handles unrelated traffic without growing the backlog."""

import asyncio
from pathlib import Path
from threading import get_ident

import pytest

from conftest import ReplayTransport, acknowledgement, sentence
from um982py import AsyncReceiver, Receiver
from um982py.async_ppp import AsyncPppSession
from um982py.commands.configuration import SignalGroup
from um982py.commands.core import action
from um982py.errors import CommandRejected, ProtocolError
from um982py.messages.frames import Message
from um982py.ppp import PppSession

GGA = sentence(b"GNGGA,145842.00,5232.0000,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,")
SIDE_BEFORE = sentence(b"GNVTG,1,T,0,M,0,N,0,K,A")
SIDE_AFTER = sentence(b"GNVTG,2,T,0,M,0,N,0,K,A")
OLD_BACKLOG = sentence(b"GNRMC,1,V,,,,,,,,,,N")
OLD_INCOMING = sentence(b"GNRMC,2,V,,,,,,,,,,N")
PPP = (Path(__file__).parent / "fixtures/captures-extra/PPPNAVB.bin").read_bytes()


def _session(receiver: Receiver) -> PppSession:
    group = SignalGroup(3, 6)
    return PppSession(receiver, "E6-HAS", group, group, True, "E6-HAS", False, False)


def _transport(command: bytes, reply: bytes) -> ReplayTransport:
    return ReplayTransport(
        {
            b"RESET\r\n": OLD_BACKLOG + acknowledgement("RESET") + OLD_INCOMING,
            command: SIDE_BEFORE * 80 + reply + SIDE_AFTER * 80,
        },
        chunk=65536,
    )


@pytest.mark.parametrize("ppp", [False, True])
def test_polling_routes_large_bursts_and_preserves_existing_backlog(ppp: bool) -> None:
    command, reply = (b"PPPNAVB\r\n", PPP) if ppp else (b"GPGGA\r\n", GGA)
    transport = _transport(command, reply)
    side: list[bytes] = []
    with Receiver(transport, queue_limit=3) as receiver:
        receiver.execute(action("RESET"))
        iterator = (
            _session(receiver).positions(
                interval=0.001, on_message=lambda m: side.append(m.raw)
            )
            if ppp
            else receiver.positions(
                interval=0.001, on_message=lambda m: side.append(m.raw)
            )
        )
        assert next(iterator).valid
        assert next(iterator).valid
        iterator.close()
        assert side == (80 * [SIDE_BEFORE] + 80 * [SIDE_AFTER]) * 2
        assert [message.raw for message in receiver.drain_pending()] == [
            OLD_BACKLOG,
            OLD_INCOMING,
        ]


@pytest.mark.parametrize("ppp", [False, True])
def test_polling_discards_new_unrelated_messages_by_default(ppp: bool) -> None:
    command, reply = (b"PPPNAVB\r\n", PPP) if ppp else (b"GPGGA\r\n", GGA)
    with Receiver(_transport(command, reply), queue_limit=1) as receiver:
        iterator = (
            _session(receiver).positions(interval=0.001)
            if ppp
            else receiver.positions(interval=0.001)
        )
        assert next(iterator).valid
        assert next(iterator).valid
        iterator.close()
        assert receiver.drain_pending() == ()


@pytest.mark.parametrize("ppp", [False, True])
def test_polling_checks_rejection_even_after_a_matching_response(ppp: bool) -> None:
    command, reply = (b"PPPNAVB\r\n", PPP) if ppp else (b"GPGGA\r\n", GGA)
    command_text = command.decode().strip()
    rejection = acknowledgement(command_text, "INVALID PARAMETER")
    transport = ReplayTransport({command: SIDE_BEFORE + reply + rejection}, chunk=65536)
    side: list[Message] = []
    with Receiver(transport) as receiver:
        iterator = (
            _session(receiver).positions(on_message=side.append)
            if ppp
            else receiver.positions(on_message=side.append)
        )
        with pytest.raises(CommandRejected):
            next(iterator)
    assert [message.raw for message in side] == [SIDE_BEFORE, rejection]


def test_poll_callback_cannot_start_a_nested_receiver_transaction() -> None:
    transport = ReplayTransport({b"GPGGA\r\n": SIDE_BEFORE + GGA}, chunk=65536)
    with Receiver(transport) as receiver:

        def callback(message: Message) -> None:
            del message
            receiver.fix()

        with pytest.raises(RuntimeError, match="on_message"):
            next(receiver.positions(on_message=callback))
        assert transport.writes == [b"GPGGA\r\n"]


def test_poll_callback_receives_only_other_messages_when_position_is_invalid() -> None:
    invalid = sentence(
        b"GNGGA,145842.00,invalid,N,01322.0000,E,1,17,1.3,38.0,M,36.0,M,,"
    )
    transport = ReplayTransport(
        {b"GPGGA\r\n": SIDE_BEFORE + invalid + SIDE_AFTER}, chunk=65536
    )
    received: list[Message] = []
    with (
        Receiver(transport) as receiver,
        pytest.raises(ProtocolError, match="Invalid GGA"),
    ):
        next(receiver.positions(on_message=received.append))
    assert [message.raw for message in received] == [SIDE_BEFORE, SIDE_AFTER]


def test_polling_preserves_a_frame_partly_buffered_before_the_query() -> None:
    split = len(SIDE_BEFORE) // 2
    transport = ReplayTransport(
        {b"GPGGA\r\n": SIDE_BEFORE[split:] + GGA + SIDE_AFTER}, chunk=65536
    )
    received: list[bytes] = []
    with Receiver(transport, queue_limit=1) as receiver:
        assert receiver.decoder.feed(SIDE_BEFORE[:split]) == ()
        position = next(
            receiver.positions(on_message=lambda message: received.append(message.raw))
        )
        assert position.valid
        assert received == [SIDE_AFTER]
        assert [message.raw for message in receiver.drain_pending()] == [SIDE_BEFORE]


def test_polling_recovers_a_reply_after_a_damaged_preexisting_partial_frame() -> None:
    transport = ReplayTransport({b"GPGGA\r\n": GGA}, chunk=65536)
    with Receiver(transport, queue_limit=1) as receiver:
        assert receiver.decoder.feed(b"$GNRMC,damaged") == ()
        assert next(receiver.positions()).valid
        assert receiver.drain_pending() == ()


@pytest.mark.parametrize("ppp", [False, True])
def test_async_polling_calls_back_on_worker_and_keeps_old_messages(ppp: bool) -> None:
    async def run() -> None:
        command, reply = (b"PPPNAVB\r\n", PPP) if ppp else (b"GPGGA\r\n", GGA)
        transport = _transport(command, reply)
        receiver = Receiver(transport, queue_limit=3)
        receiver.execute(action("RESET"))
        asynchronous = AsyncReceiver(receiver)
        loop_thread = get_ident()
        callback_threads: list[int] = []
        side: list[bytes] = []

        def callback(message: Message) -> None:
            callback_threads.append(get_ident())
            side.append(message.raw)

        if ppp:
            session = AsyncPppSession(asynchronous, _session(receiver))
            iterator = session.positions(interval=0.001, on_message=callback)
        else:
            iterator = asynchronous.positions(interval=0.001, on_message=callback)
        assert (await anext(iterator)).valid
        assert (await anext(iterator)).valid
        await iterator.aclose()
        assert callback_threads and all(
            thread != loop_thread for thread in callback_threads
        )
        assert side == (80 * [SIDE_BEFORE] + 80 * [SIDE_AFTER]) * 2
        assert [message.raw for message in await asynchronous.drain_pending()] == [
            OLD_BACKLOG,
            OLD_INCOMING,
        ]
        await asynchronous.close()

    asyncio.run(run())
