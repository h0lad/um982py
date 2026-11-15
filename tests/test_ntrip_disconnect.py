from io import BytesIO
from unittest.mock import patch

import pytest

from conftest import sentence
from um982py.ntrip import (
    NtripClient,
    NtripDisconnected,
    NtripError,
    retryable_ntrip_error,
)


class Socket:
    def __init__(self, response: bytes) -> None:
        self.response = BytesIO(response)

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        pass

    def recv(self, size: int) -> bytes:
        return self.response.read(size)

    def close(self) -> None:
        pass


@pytest.mark.parametrize("body", [b"5\r\nab", b"2\r\nab\r", b"2\r\nab\r\n3"])
def test_truncated_chunk_is_a_retryable_disconnect(body: bytes) -> None:
    response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + body
    with (
        patch("socket.create_connection", return_value=Socket(response)),
        NtripClient("http://caster.test:2101/BASE") as client,
    ):
        assert client.read() == b"ab"
        with pytest.raises(NtripDisconnected) as caught:
            client.read()
    assert retryable_ntrip_error(caught.value)


def test_gga_requires_valid_fields_and_checksum() -> None:
    valid = sentence(b"GPGGA,1,4807.038,N,01131.000,E,1,12,1,1,M,1,M,,0")
    NtripClient("http://caster.test/BASE", initial_gga=valid)
    invalid = (
        valid[:-4] + b"00\r\n",
        sentence(b"GPGGA,1"),
        b"$GPGGA,broken\r\n",
    )
    for value in invalid:
        with pytest.raises(ValueError, match="GPGGA"):
            NtripClient("http://caster.test/BASE", initial_gga=value)


@pytest.mark.parametrize("size", [b"+2", b"0x2", b"1_0", b" 2", b"2 ", b"-0"])
def test_chunk_size_requires_wire_hex_digits(size: bytes) -> None:
    response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
    with (
        patch(
            "socket.create_connection", return_value=Socket(response + size + b"\r\nab")
        ),
        NtripClient("http://caster.test/BASE") as client,
        pytest.raises(NtripError, match="chunk size"),
    ):
        client.read()


@pytest.mark.parametrize("ending", [b"0\r\n", b"0\r\nExample: value\r\n"])
def test_chunked_eof_requires_complete_trailers(ending: bytes) -> None:
    response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + ending
    with (
        patch("socket.create_connection", return_value=Socket(response)),
        NtripClient("http://caster.test/BASE") as client,
        pytest.raises(NtripDisconnected),
    ):
        client.read()


def test_chunked_trailers_resume_after_timeout() -> None:
    response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
    peer = Socket(response + b"2;tag=yes\r\nab\r\n0\r\nExample: value\r\n")
    with (
        patch("socket.create_connection", return_value=peer),
        NtripClient("http://caster.test/BASE") as client,
    ):
        assert client.read(1) == b"a"
        assert client.read(1) == b"b"
        with (
            patch.object(peer, "recv", side_effect=TimeoutError),
            pytest.raises(TimeoutError),
        ):
            client.read()
        peer.response = BytesIO(b"Another: value\r\n\r\n")
        assert client.read() == b""
        assert client.read() == b""


def test_chunked_trailers_are_bounded() -> None:
    response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
    peer = Socket(response + b"0\r\n" + b"X: value\r\n" * 2000 + b"\r\n")
    with (
        patch("socket.create_connection", return_value=peer),
        NtripClient("http://caster.test/BASE") as client,
        pytest.raises(NtripError, match="trailers exceed"),
    ):
        client.read()
