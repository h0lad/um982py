"""The incremental protocol decoding API."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.protocol.decoder import StreamDecoder

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "StreamDecoder": ("um982py.protocol.decoder", "StreamDecoder"),
}

__all__ = ["StreamDecoder"]


def __getattr__(name: str) -> object:
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    target = import_module(module)
    value = target if attribute is None else getattr(target, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
