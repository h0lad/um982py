from collections import deque
from pathlib import Path

import pytest

from um982py.commands.types import Port, Trigger
from um982py.protocol.checksums import nmea_checksum, rtcm_crc24q, unicore_crc32

FIXTURES = Path(__file__).parent / "fixtures"


def sentence(body: bytes) -> bytes:
    return b"$" + body + f"*{nmea_checksum(body):02X}\r\n".encode()


def acknowledgement(command: str, status: str = "OK") -> bytes:
    body = f"$command,{command},response: {status}".encode()
    return body + f"*{nmea_checksum(body):02X}\r\n".encode()


def rtcm(payload: bytes) -> bytes:
    body = b"\xd3" + len(payload).to_bytes(2, "big") + payload
    return body + rtcm_crc24q(body).to_bytes(3, "big")


def ascii_message(name: str, fields: str) -> bytes:
    body = f"{name},98,GPS,FINE,2400,123000,2400,0,18,1;{fields}".encode()
    return b"#" + body + f"*{unicore_crc32(body):08x}\r\n".encode()


class ReplayTransport:
    def __init__(
        self, responses: dict[bytes, bytes] | None = None, *, chunk: int = 7
    ) -> None:
        self.responses = responses or {}
        self.chunk = chunk
        self.pending: deque[int] = deque()
        self.writes: list[bytes] = []
        self.closed = False

    def read(self, size: int, timeout: float) -> bytes:
        del timeout
        return bytes(
            self.pending.popleft()
            for _ in range(min(size, self.chunk, len(self.pending)))
        )

    def write(self, data: bytes, timeout: float) -> None:
        del timeout
        self.writes.append(data)
        self.pending.extend(self.responses.get(data, b""))

    def close(self) -> None:
        self.closed = True


class SubscriptionTransport(ReplayTransport):
    """Model log changes independently of receiver transactions."""

    def __init__(self) -> None:
        super().__init__(chunk=65536)
        self.subscriptions: dict[tuple[str, Port], float | Trigger] = {}
        self.rejected: set[str] = set()
        self.silent: set[str] = set()
        self.after_write: dict[str, bytes] = {}

    def write(self, data: bytes, timeout: float) -> None:
        del timeout
        self.writes.append(data)
        command = data.decode("ascii").strip()
        parts = command.split()
        if command in self.rejected:
            response = acknowledgement(command, "INVALID PARAMETER")
        elif command == "LOGLISTA":
            records = ",".join(
                f'"{name} {port.value} {interval}"'
                for (name, port), interval in self.subscriptions.items()
            )
            fields = str(len(self.subscriptions)) + ("," + records if records else "")
            response = ascii_message("LOGLISTA", fields)
        else:
            if parts[0] == "UNLOG":
                port = Port(parts[1]) if len(parts) == 3 else Port.COM1
                self.subscriptions.pop((parts[-1], port), None)
            else:
                port = Port(parts[1]) if len(parts) == 3 else Port.COM1
                interval = (
                    Trigger.ON_CHANGED
                    if parts[-1] == Trigger.ON_CHANGED
                    else float(parts[-1])
                )
                self.subscriptions[parts[0], port] = interval
            response = acknowledgement(command)
        if command not in self.silent:
            self.pending.extend(response)
        self.pending.extend(self.after_write.get(command, b""))


@pytest.fixture
def replay() -> ReplayTransport:
    return ReplayTransport()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--hardware-port", default=None)
    parser.addoption("--hardware-baud", type=int, default=921600)
    parser.addoption("--soak-seconds", type=float, default=10)
    parser.addoption("--acquisition-seconds", type=float, default=5)
    parser.addoption("--hardware-report", default="hardware-report.json")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--hardware-port"):
        return
    skip = pytest.mark.skip(reason="select a receiver with --hardware-port")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
