"""Receiver, rover and observation workflows.

Specialist APIs are imported from their defining submodules. See the API guide
in README.md for streaming, reconnection, antenna routing and data formats.
"""

from collections.abc import Callable as _Callable
from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from um982py.async_receiver import AsyncReceiver as AsyncReceiver
    from um982py.capture import capture_live as capture_live
    from um982py.capture import load_records as load_records
    from um982py.commands import Log as Log
    from um982py.decode import decode_message as decode_message
    from um982py.messages.navigation import Position as Position
    from um982py.observations import Observations as Observations
    from um982py.observations import record_observations as record_observations
    from um982py.receiver import Receiver as Receiver
    from um982py.rover import Rover as Rover

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "AsyncReceiver": ("um982py.async_receiver", "AsyncReceiver"),
    "Log": ("um982py.commands", "Log"),
    "Observations": ("um982py.observations", "Observations"),
    "Position": ("um982py.messages.navigation", "Position"),
    "Receiver": ("um982py.receiver", "Receiver"),
    "Rover": ("um982py.rover", "Rover"),
    "capture_live": ("um982py.capture", "capture_live"),
    "decode_message": ("um982py.decode", "decode_message"),
    "load_records": ("um982py.capture", "load_records"),
    "record_observations": ("um982py.observations", "record_observations"),
}

__all__ = [
    "AsyncReceiver",
    "Log",
    "Observations",
    "Position",
    "Receiver",
    "Rover",
    "capture_live",
    "decode_message",
    "load_records",
    "record_observations",
]


def _lazy_exports(
    namespace: dict[str, object], exports: dict[str, tuple[str, str | None]]
) -> tuple[_Callable[[str], object], _Callable[[], list[str]]]:
    """Build a package's ``__getattr__`` and ``__dir__`` for on-demand imports.

    Each export names its module and attribute, or None to export the module.
    """

    def getattr_(name: str) -> object:
        try:
            module, attribute = exports[name]
        except KeyError:
            raise AttributeError(
                f"module {namespace['__name__']!r} has no attribute {name!r}"
            ) from None
        target = _import_module(module)
        value = target if attribute is None else getattr(target, attribute)
        namespace[name] = value
        return value

    def dir_() -> list[str]:
        return sorted(set(namespace) | set(exports))

    return getattr_, dir_


__getattr__, __dir__ = _lazy_exports(globals(), _EXPORTS)
