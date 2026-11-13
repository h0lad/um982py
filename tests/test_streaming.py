from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from conftest import acknowledgement, rtcm, sentence
from um982py.commands.core import action
from um982py.errors import TransportClosed
from um982py.live import PositionSubscription
from um982py.protocol.binary import parse_rtcm
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


def test_stream_context_starts_and_stops_without_closing_receiver() -> None:
    transport = QueueTransport()
    receiver = Receiver(transport)
    with (
        pytest.raises(RuntimeError, match="application error"),
        ReceiverStream(receiver) as stream,
    ):
        assert stream.health().running
        raise RuntimeError("application error")
    assert not stream.health().running
    assert not transport.closed
    receiver.close()
    assert transport.closed


def test_running_stream_owns_receiver_and_releases_it_after_close() -> None:
    receiver = Receiver(QueueTransport())
    stream = ReceiverStream(receiver)
    stream.start()
    try:
        with pytest.raises(RuntimeError, match="owned"):
            receiver.receive(timeout=0.01)
        with pytest.raises(RuntimeError, match="owned"):
            receiver.close()
        with pytest.raises(RuntimeError, match="owned"):
            _ = receiver.transport
        with pytest.raises(RuntimeError, match="owned"):
            _ = receiver.decoder
        with pytest.raises(RuntimeError, match="owned"):
            ReceiverStream(receiver).start()
    finally:
        stream.close()
    receiver.close()


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
        stream.unsubscribe(subscriber)
        assert stream.health().subscription_drops == 1
    finally:
        stream.close(close_receiver=True)
    assert transport.closed


def test_stream_preserves_frame_completion_time_during_slow_command() -> None:
    class SlowCommand(QueueTransport):
        def __init__(self) -> None:
            super().__init__()
            self.delivered = Event()

        def write(self, data: bytes, timeout: float) -> None:
            self.writes.append(data)
            self.incoming.put(sentence(b"GPGGA,1"))

        def read(self, size: int, timeout: float) -> bytes:
            data = super().read(size, timeout)
            if data.startswith(b"$GPGGA"):
                self.delivered.set()
            return data

    transport = SlowCommand()
    stream = ReceiverStream(Receiver(transport), poll_seconds=0.01)
    subscriber = stream.subscribe()
    stream.start()
    try:
        pending = stream.execute(action("RESET"))
        assert transport.delivered.wait(1)
        sleep(0.05)
        transport.incoming.put(acknowledgement("RESET"))
        assert pending.result(timeout=1).accepted
        event = subscriber.get_event(timeout=1)
        assert event.dispatched_monotonic - event.received_monotonic >= 0.04
        assert event.session_id == stream.session_id
    finally:
        stream.close(close_receiver=True)


def test_stream_reports_disconnect_and_rejects_new_work() -> None:
    transport = QueueTransport()
    stream = ReceiverStream(Receiver(transport), poll_seconds=0.01)
    stream.start()
    transport.incoming.put(None)
    wait_for(lambda: not stream.health().running)
    assert "disconnected" in (stream.health().failure or "")
    with pytest.raises(TransportClosed, match="stream stopped"):
        stream.execute(action("RESET"))
    stream.close()


def test_closing_stream_wakes_an_idle_subscriber() -> None:
    stream = ReceiverStream(Receiver(QueueTransport()), poll_seconds=0.01)
    subscriber = stream.subscribe()
    finished = Event()

    def consume() -> None:
        try:
            subscriber.get()
        except TransportClosed:
            finished.set()

    stream.start()
    consumer = Thread(target=consume)
    consumer.start()
    stream.close()
    assert finished.wait(1)
    consumer.join()
    with pytest.raises(RuntimeError):
        stream.subscribe()


def test_stream_cannot_start_after_close() -> None:
    stream = ReceiverStream(Receiver(QueueTransport()))
    stream.close()
    with pytest.raises(RuntimeError, match="stopped"):
        stream.start()


def test_position_subscription_filters_and_tracks_drops() -> None:
    transport = QueueTransport()
    stream = ReceiverStream(Receiver(transport), poll_seconds=0.01)
    positions = PositionSubscription(stream, capacity=1)
    stream.start()
    gga = sentence(
        b"GPGGA,123519,4807.038,N,01131.000,E,4,08,0.9,545.4,M,46.9,M,1.2,0001"
    )
    transport.incoming.put(sentence(b"GPRMC,1") + gga + gga)
    try:
        wait_for(lambda: stream.health().messages == 3)
        update = positions.get(timeout=1)
        assert update.fix.quality == 4 and update.connection == 1
        assert update.received_at.utcoffset().total_seconds() == 0
        assert update.received_monotonic <= monotonic()
        assert positions.dropped == 1
    finally:
        positions.close()
        stream.close(close_receiver=True)


def test_positions_and_correction_writes_share_one_receiver_stream() -> None:
    class CorrectionTransport(QueueTransport):
        def write(self, data: bytes, timeout: float) -> None:
            del timeout
            self.writes.append(data)
            self.incoming.put(
                sentence(
                    b"GPGGA,123519,4807.038,N,01131.000,E,4,08,0.9,"
                    b"545.4,M,46.9,M,1.2,0001"
                )
            )

    transport = CorrectionTransport()
    stream = ReceiverStream(Receiver(transport), poll_seconds=0.01)
    positions = PositionSubscription(stream)
    stream.start()
    correction = rtcm(b"\x3e\xd0")
    try:
        stream.send_correction(parse_rtcm(correction)).result(timeout=2)
        assert positions.get(timeout=1).fix.quality == 4
        assert transport.writes == [correction]
    finally:
        positions.close()
        stream.close(close_receiver=True)
