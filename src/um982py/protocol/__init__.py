"""The incremental protocol decoding API."""

from typing import TYPE_CHECKING

from um982py import _lazy_exports

if TYPE_CHECKING:
    from um982py.protocol.decoder import StreamDecoder

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "StreamDecoder": ("um982py.protocol.decoder", "StreamDecoder"),
}

__all__ = ["StreamDecoder"]


__getattr__, __dir__ = _lazy_exports(globals(), _EXPORTS)
