"""The frame, record and decoder API."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.messages.decode import decode_log
    from um982py.messages.frames import (
        AsciiHeader,
        AsciiMessage,
        BinaryHeader,
        BinaryMessage,
        CommandResponse,
        LegacyAsciiHeader,
        LegacyBinaryHeader,
        LogListMessage,
        Message,
        RtcmMessage,
        Sentence,
        TextLine,
    )
    from um982py.messages.navigation import BestNavigation, Fix, Heading
    from um982py.messages.observations import Observation, TrackingStatus
    from um982py.messages.record import Record, Value
    from um982py.messages.version import Version

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "AsciiHeader": ("um982py.messages.frames", "AsciiHeader"),
    "AsciiMessage": ("um982py.messages.frames", "AsciiMessage"),
    "BestNavigation": ("um982py.messages.navigation", "BestNavigation"),
    "BinaryHeader": ("um982py.messages.frames", "BinaryHeader"),
    "BinaryMessage": ("um982py.messages.frames", "BinaryMessage"),
    "CommandResponse": ("um982py.messages.frames", "CommandResponse"),
    "Fix": ("um982py.messages.navigation", "Fix"),
    "Heading": ("um982py.messages.navigation", "Heading"),
    "LegacyAsciiHeader": ("um982py.messages.frames", "LegacyAsciiHeader"),
    "LegacyBinaryHeader": ("um982py.messages.frames", "LegacyBinaryHeader"),
    "LogListMessage": ("um982py.messages.frames", "LogListMessage"),
    "Message": ("um982py.messages.frames", "Message"),
    "Observation": ("um982py.messages.observations", "Observation"),
    "Record": ("um982py.messages.record", "Record"),
    "RtcmMessage": ("um982py.messages.frames", "RtcmMessage"),
    "Sentence": ("um982py.messages.frames", "Sentence"),
    "TextLine": ("um982py.messages.frames", "TextLine"),
    "TrackingStatus": ("um982py.messages.observations", "TrackingStatus"),
    "Value": ("um982py.messages.record", "Value"),
    "Version": ("um982py.messages.version", "Version"),
    "decode_log": ("um982py.messages.decode", "decode_log"),
}

__all__ = [
    "AsciiHeader",
    "AsciiMessage",
    "BestNavigation",
    "BinaryHeader",
    "BinaryMessage",
    "CommandResponse",
    "Fix",
    "Heading",
    "LegacyAsciiHeader",
    "LegacyBinaryHeader",
    "LogListMessage",
    "Message",
    "Observation",
    "Record",
    "RtcmMessage",
    "Sentence",
    "TextLine",
    "TrackingStatus",
    "Value",
    "Version",
    "decode_log",
]


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
