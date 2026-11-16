"""Receiver, rover and observation workflows.

Specialist APIs are imported from their defining submodules. See the API guide
in README.md for streaming, reconnection, antenna routing and data formats.
"""

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

_EXPORTS: dict[str, str] = {
    "AsyncReceiver": "um982py.async_receiver",
    "Log": "um982py.commands",
    "Observations": "um982py.observations",
    "Position": "um982py.messages.navigation",
    "Receiver": "um982py.receiver",
    "Rover": "um982py.rover",
    "capture_live": "um982py.capture",
    "decode_message": "um982py.decode",
    "load_records": "um982py.capture",
    "record_observations": "um982py.observations",
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


def __getattr__(name: str) -> object:
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(_import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
