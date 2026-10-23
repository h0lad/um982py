"""The transport protocol for receiver byte streams."""

from typing import Protocol


class Transport(Protocol):
    """A byte transport that reads at most size bytes and consumes none for zero."""

    def read(self, size: int, timeout: float) -> bytes: ...

    def write(self, data: bytes, timeout: float) -> None: ...

    def close(self) -> None: ...
