import socket
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest
import serial

from conftest import acknowledgement
from um982py import Receiver
from um982py.commands import logging
from um982py.errors import TransportClosed, TransportError
from um982py.transports import SerialTransport, TcpTransport


@pytest.mark.parametrize("kind", ["serial", "tcp"])
def test_zero_length_read_does_not_consume_or_disconnect(kind: str) -> None:
    peer = MagicMock()
    if kind == "serial":
        with patch("serial.serial_for_url", return_value=peer):
            transport = SerialTransport("test")
    else:
        with patch("socket.create_connection", return_value=peer):
            transport = TcpTransport("localhost", 123)
    assert transport.read(0, 1) == b""
    with pytest.raises(ValueError, match="non-negative"):
        transport.read(-1, 1)
    peer.read.assert_not_called()
    peer.recv.assert_not_called()
    transport.close()
    with pytest.raises(TransportClosed):
        transport.read(0, 1)


@pytest.mark.parametrize(
    "error", [OSError("gone"), ValueError("bad baud"), serial.SerialException("busy")]
)
def test_serial_open_error(error: Exception) -> None:
    with (
        patch("serial.serial_for_url", side_effect=error),
        pytest.raises(TransportError) as caught,
    ):
        SerialTransport("missing")
    assert str(error) in str(caught.value)


def test_serial_reads_writes_and_closes() -> None:
    peer = MagicMock()
    peer.read.side_effect = [b"a", b"bc", b""]
    peer.in_waiting = 2
    peer.write.side_effect = [1, 2]
    with patch("serial.serial_for_url", return_value=peer):
        transport = SerialTransport("test")
        assert transport.read(3, 0.1) == b"abc"
        assert transport.read(3, 0.1) == b""
        transport.write(b"abc", 1)
        assert peer.write.call_args_list[1].args == (b"bc",)
        transport.close()
        transport.close()
        peer.close.assert_called_once()
        with pytest.raises(TransportClosed):
            transport.read(1, 0.1)


def test_serial_failures() -> None:
    with patch("serial.serial_for_url", return_value=MagicMock()) as factory:
        transport = SerialTransport("test")
        peer = factory.return_value
        peer.read.side_effect = serial.SerialException("gone")
        with pytest.raises(TransportError):
            transport.read(1, 0.1)
        peer.write.return_value = 0
        with pytest.raises(TransportError, match="progress"):
            transport.write(b"x", 0.1)
        with pytest.raises(TransportError, match="timed out"):
            transport.write(b"x", 0)
        peer.write.side_effect = serial.SerialTimeoutException("timeout")
        with pytest.raises(TransportError):
            transport.write(b"x", 0.1)


def test_tcp_contract() -> None:
    peer = MagicMock()
    with patch("socket.create_connection", return_value=peer):
        transport = TcpTransport("localhost", 123)
        peer.recv.return_value = b"ab"
        assert transport.read(2, 1) == b"ab"
        peer.recv.side_effect = TimeoutError
        assert transport.read(1, 0.1) == b""
        peer.recv.side_effect = OSError
        with pytest.raises(TransportError):
            transport.read(1, 0.1)
        peer.recv.side_effect = None
        peer.recv.return_value = b""
        with pytest.raises(TransportClosed):
            transport.read(1, 0.1)
        transport.write(b"abc", 1)
        peer.sendall.assert_called_once_with(b"abc")
        peer.sendall.side_effect = OSError
        with pytest.raises(TransportError):
            transport.write(b"abc", 1)
        transport.close()
        transport.close()
        peer.close.assert_called_once()
        with pytest.raises(TransportClosed):
            transport.write(b"x", 1)
    with (
        patch("socket.create_connection", side_effect=OSError),
        pytest.raises(TransportError),
    ):
        TcpTransport("localhost", 123)


def test_receiver_factories() -> None:
    with patch("um982py.receiver.SerialTransport") as factory:
        receiver = Receiver.serial("test", 921600)
        assert receiver.transport is factory.return_value
    with patch("um982py.receiver.TcpTransport") as factory:
        receiver = Receiver.tcp("localhost", 123)
        assert receiver.transport is factory.return_value


def test_receiver_target_selection() -> None:
    with patch.object(Receiver, "serial") as serial_factory:
        Receiver.connect("/dev/ttyUSB0", 921600, timeout=2)
        serial_factory.assert_called_once_with("/dev/ttyUSB0", 921600, timeout=2)
    with patch.object(Receiver, "tcp") as tcp_factory:
        Receiver.connect("tcp://192.0.2.10:4001", 921600, timeout=2)
        tcp_factory.assert_called_once_with("192.0.2.10", 4001, timeout=2)
        Receiver.connect("TCP://[::1]:4002")
        tcp_factory.assert_called_with("::1", 4002, timeout=3)


@pytest.mark.parametrize(
    "target",
    (
        "tcp://",
        "tcp://gateway",
        "tcp://gateway:0",
        "tcp://gateway:65536",
        "tcp://gateway:abc",
        "tcp://user@gateway:4001",
        "tcp://gateway:4001/path",
        "tcp://gateway:4001?mode=telnet",
        "tcp://gateway:4001#fragment",
        "tcp://[::1",
    ),
)
def test_invalid_tcp_target(target: str) -> None:
    with pytest.raises(ValueError, match="TCP target must be"):
        Receiver.connect(target)


def test_tcp_gateway_round_trip() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        received = []

        def serve() -> None:
            with listener.accept()[0] as peer:
                peer.settimeout(2)
                data = bytearray()
                while not data.endswith(b"\r\n"):
                    data.extend(peer.recv(64))
                received.append(bytes(data))
                peer.sendall(acknowledgement("UNLOG"))

        worker = Thread(target=serve, daemon=True)
        worker.start()
        with Receiver.connect(
            f"tcp://127.0.0.1:{listener.getsockname()[1]}"
        ) as receiver:
            receiver.execute(logging.stop())
        worker.join(2)
        assert not worker.is_alive()
        assert received == [b"UNLOG\r\n"]
