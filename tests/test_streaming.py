from queue import Empty, Queue
from time import monotonic, sleep

import pytest

from conftest import acknowledgement, sentence
from um982py.commands.core import action
from um982py.errors import TransportClosed
from um982py.receiver import Receiver
from um982py.streaming import ReceiverStream


class QueueTransport:
    def __init__(self) -> None:
        self.incoming: Queue[bytes | None] = Queue()
        self.writes: list[bytes] = []
        self.closed = False

    def read(self, size: int, timeout: float) -> bytes:
        del size
        try:
            item = self.incoming.get(timeout=timeout)
        except Empty:
            return b""
        if item is None:
            raise TransportClosed("disconnected")
        return item

    def write(self, data: bytes, timeout: float) -> None:
        del timeout
        self.writes.append(data)
        self.incoming.put(sentence(b"GPGGA,1") + acknowledgement("RESET"))

    def close(self) -> None:
        self.closed = True


def wait_for(predicate: object) -> None:
    deadline = monotonic() + 2
    while not predicate():  # type: ignore[operator]
        assert monotonic() < deadline
        sleep(0.005)


def test_stream_dispatches_command_backlog_and_counts_slow_consumer() -> None:
    transport = QueueTransport()
    stream = ReceiverStream(Receiver(transport, timeout=1), poll_seconds=0.01)
    subscriber = stream.subscribe(capacity=1)
    stream.start()
    try:
        assert stream.execute(action("RESET")).result(timeout=2).accepted
        wait_for(lambda: subscriber.pending == 1)
        transport.incoming.put(sentence(b"GPRMC,2"))
        wait_for(lambda: stream.health().messages == 2)
        assert subscriber.dropped == stream.health().subscription_drops == 1
        assert subscriber.get(timeout=1).raw == sentence(b"GPGGA,1")
    finally:
        stream.close(close_receiver=True)
    assert transport.closed


def test_stream_reports_disconnect_and_rejects_new_work() -> None:
    transport = QueueTransport()
    stream = ReceiverStream(Receiver(transport), poll_seconds=0.01)
    stream.start()
    transport.incoming.put(None)
    wait_for(lambda: not stream.health().running)
    assert "disconnected" in (stream.health().failure or "")
    with pytest.raises(RuntimeError):
        stream.execute(action("RESET"))
    stream.close()
