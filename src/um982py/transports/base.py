"""The transport protocol for receiver byte streams."""

from typing import Protocol


class Transport(Protocol):
    """A byte transport; a zero timeout reads only immediately available bytes."""

    def read(self, size: int, timeout: float) -> bytes: ...

    def write(self, data: bytes, timeout: float) -> None: ...

    def close(self) -> None: ...
