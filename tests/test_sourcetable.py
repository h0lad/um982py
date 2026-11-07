from io import BytesIO
from unittest.mock import patch

import pytest

from um982py.ntrip import (
    NtripClient,
    NtripClientPool,
    NtripDisconnected,
    NtripError,
    fetch_sourcetable,
    parse_sourcetable,
)

SOURCE = (
    "STR;BASE;Example;RTCM 3.2;1005(10),1077(1);2;GPS+GLO+GAL;NET;DEU;"
    "50.0;8.0;1;0;receiver;none;B;N;9600;misc\r\n"
)


class Socket:
    def __init__(self, response: bytes) -> None:
        self.response = BytesIO(response)
        self.sent = b""
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, size: int) -> bytes:
        return self.response.read(size)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("status", [b"SOURCETABLE 200 OK", b"HTTP/1.1 200 OK"])
def test_fetch_sourcetable_v1_and_v2(status: bytes) -> None:
    socket = Socket(
        status
        + b"\r\nContent-Type: text/plain\r\n\r\n"
        + SOURCE.encode()
        + b"ENDSOURCETABLE\r\n"
    )
    with patch("socket.create_connection", return_value=socket):
        sources = fetch_sourcetable("http://caster.test:2101", version=1)
    assert socket.sent.startswith(b"GET / HTTP/1.0\r\n")
    assert socket.closed
    assert len(sources) == 1
    source = sources[0]
    assert source.name == "BASE" and source.systems == ("GPS", "GLO", "GAL")
    assert source.requires_gga and source.bitrate == 9600
    assert source.distance_to(50, 8) == pytest.approx(0)


def test_parse_unknown_location_and_bad_values() -> None:
    source = parse_sourcetable(SOURCE.replace("50.0;8.0;1", ";;"))[0]
    assert source.distance_to(50, 8) is None and source.requires_gga is None
    with pytest.raises(NtripError, match="STR value"):
        parse_sourcetable(SOURCE.replace("50.0;8.0", "nan;8.0"))
    with pytest.raises(NtripError, match="STR record"):
        parse_sourcetable("STR;invalid")


def test_fetch_rejects_truncated_and_oversized_sourcetable() -> None:
    response = b"HTTP/1.1 200 OK\r\n\r\n" + SOURCE.encode()
    with (
        patch("socket.create_connection", return_value=Socket(response)),
        pytest.raises(NtripDisconnected),
    ):
        fetch_sourcetable("http://caster.test")
    with (
        patch("socket.create_connection", return_value=Socket(response)),
        pytest.raises(NtripError, match="size limit"),
    ):
        fetch_sourcetable("http://caster.test", max_bytes=10)


def test_sourcetable_requires_caster_root() -> None:
    with pytest.raises(ValueError, match="URL"):
        fetch_sourcetable("http://caster.test/BASE")


def test_client_pool_rotates_fresh_clients() -> None:
    pool = NtripClientPool(
        [
            lambda: NtripClient("http://caster.test/A"),
            lambda: NtripClient("http://caster.test/B"),
        ]
    )
    assert [pool().mountpoint for _ in range(3)] == ["/A", "/B", "/A"]
    with pytest.raises(ValueError, match="factory"):
        NtripClientPool([])
