from math import nan

import pytest

from conftest import ReplayTransport, acknowledgement, rtcm, sentence
from um982py import Receiver
from um982py.commands import queries
from um982py.commands.core import action
from um982py.errors import (
    BufferOverflow,
    CommandRejected,
    ResponseTimeout,
)
from um982py.protocol import StreamDecoder
from um982py.protocol.binary import parse_rtcm


def test_reply_available_at_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])

    class DeadlineTransport(ReplayTransport):
        def read(self, size: int, timeout: float) -> bytes:
            clock[0] = 1.0
            return super().read(size, timeout)

    transport = DeadlineTransport({b"RESET\r\n": acknowledgement("RESET")}, chunk=1000)
    with Receiver(transport, timeout=1) as receiver:
        assert receiver.execute(action("RESET")).accepted


def test_acknowledgement_negative_and_timeout() -> None:
    transport = ReplayTransport(
        {b"RESET\r\n": acknowledgement("RESET", "INVALID PARAMETER")}
    )
    receiver = Receiver(transport, timeout=0.01)
    with pytest.raises(CommandRejected) as caught:
        receiver.execute(action("RESET"))
    assert caught.value.command == "RESET"
    assert caught.value.response == "INVALID PARAMETER"
    with pytest.raises(ResponseTimeout):
        receiver.execute(action("VERSION"))
    with pytest.raises(ResponseTimeout):
        receiver.receive()
    with pytest.raises(ResponseTimeout):
        receiver.collect(queries.configuration())


def test_live_missing_colon_rejection_does_not_timeout() -> None:
    command = "RAWDATAB RANGEB 1"
    raw = b"$command,RAWDATAB RANGEB 1,response can't found device (null)*31\r\n"
    transport = ReplayTransport({command.encode() + b"\r\n": raw})
    with Receiver(transport, timeout=0.01) as receiver:
        with pytest.raises(CommandRejected) as caught:
            receiver.execute(action(command))
        assert caught.value.response == "can't found device (null)"
        assert not receiver.decoder.errors


@pytest.mark.parametrize("method", ["execute", "collect"])
@pytest.mark.parametrize("echo", ["$reset", "  $ReSeT  "])
def test_prefixed_rejection_raises(method: str, echo: str) -> None:
    transport = ReplayTransport(
        {b"RESET\r\n": acknowledgement(echo, "INVALID PARAMETER")}
    )
    with (
        Receiver(transport, timeout=0.01) as receiver,
        pytest.raises(CommandRejected) as caught,
    ):
        getattr(receiver, method)(action("RESET"))
    assert caught.value.command == "RESET"
    assert caught.value.response == "INVALID PARAMETER"


def test_prefixed_rejection_of_query_raises() -> None:
    transport = ReplayTransport(
        {b"VERSIONA\r\n": acknowledgement("$versiona", "INVALID PARAMETER")}
    )
    with Receiver(transport, timeout=0.01) as receiver, pytest.raises(CommandRejected):
        receiver.version()


def test_old_ack_is_not_reused() -> None:
    transport = ReplayTransport(
        {b"RESET\r\n": acknowledgement("RESET") + acknowledgement("RESET")}, chunk=5000
    )
    receiver = Receiver(transport, timeout=0.01)
    receiver.execute(action("RESET"))
    transport.responses.clear()
    with pytest.raises(ResponseTimeout):
        receiver.execute(action("RESET"))
    assert receiver.receive().command == "RESET"


def test_send_correction_and_checksummed_command() -> None:
    transport = ReplayTransport()
    receiver = Receiver(transport, checksummed=True)
    receiver.send(action("RESET"))
    receiver.send_correction(parse_rtcm(rtcm(b"\x3e\xd0")))
    assert transport.writes == [b"$RESET*55\r\n", rtcm(b"\x3e\xd0")]


def test_queue_overflow() -> None:
    data = sentence(b"GPGGA,1") * 5
    transport = ReplayTransport({b"RESET\r\n": data}, chunk=5000)
    with pytest.raises(BufferOverflow):
        Receiver(transport, queue_limit=2).execute(action("RESET"))
    transport = ReplayTransport({b"RESET\r\n": data}, chunk=1)
    with pytest.raises(BufferOverflow):
        Receiver(transport, queue_limit=2).execute(action("RESET"))


@pytest.mark.parametrize("timeout", [0, -1, nan])
def test_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValueError):
        Receiver(ReplayTransport(), timeout=timeout)
    receiver = Receiver(ReplayTransport())
    with pytest.raises(ValueError):
        receiver.receive(timeout=timeout)
    with pytest.raises(ValueError):
        receiver.collect(action("RESET"), quiet=timeout)


def test_queue_and_decoder_arguments() -> None:
    with pytest.raises(ValueError):
        Receiver(ReplayTransport(), queue_limit=0)
    decoder = StreamDecoder(strict=True)
    assert Receiver(ReplayTransport(), decoder=decoder).decoder is decoder


def test_drain_pending_returns_queued_messages_in_receive_order() -> None:
    before = sentence(b"GPGGA,1")
    after = sentence(b"GPRMC,2")
    transport = ReplayTransport(
        {b"RESET\r\n": before + acknowledgement("RESET") + after}, chunk=5000
    )
    with Receiver(transport, timeout=0.01) as receiver:
        assert receiver.execute(action("RESET")).accepted
        assert [message.raw for message in receiver.drain_pending()] == [before, after]
        assert receiver.drain_pending() == ()
        with pytest.raises(ResponseTimeout):
            receiver.receive()


def test_draining_pending_messages_keeps_repeated_queries_bounded() -> None:
    response = sentence(b"GPGGA,1") + acknowledgement("RESET")
    transport = ReplayTransport({b"RESET\r\n": response}, chunk=5000)
    with Receiver(transport, timeout=0.01, queue_limit=2) as receiver:
        for _ in range(10):
            assert receiver.execute(action("RESET")).accepted
            assert len(receiver.drain_pending()) == 1
