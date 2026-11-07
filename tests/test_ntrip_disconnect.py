from io import BytesIO
from unittest.mock import patch

import pytest

from um982py.ntrip import NtripClient, NtripDisconnected, retryable_ntrip_error


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
