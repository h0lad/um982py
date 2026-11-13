"""The frame, record and decoder API."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.messages.decode import decode_log
    from um982py.messages.frames import (
        AbbreviatedAsciiMessage,
        AsciiHeader,
        AsciiMessage,
        BinaryHeader,
        BinaryMessage,
        CommandResponse,
        LogListMessage,
        Message,
        OemAsciiHeader,
        OemBinaryHeader,
        RtcmMessage,
        Sentence,
        TextLine,
    )
    from um982py.messages.navigation import BestNavigation, Fix, Heading, Position
    from um982py.messages.observations import Observation, TrackingStatus
    from um982py.messages.receiver_status import (
        PpsConfigInfo,
        PpsQuality,
        PpsStatus,
        SpoofInfo,
        SpoofNotice,
        SpoofSignal,
        SpoofTimeNotice,
    )
    from um982py.messages.record import Record, Value
    from um982py.messages.version import Version
    from um982py.precision import ErrorEllipse, PositionPrecision

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "AbbreviatedAsciiMessage": ("um982py.messages.frames", "AbbreviatedAsciiMessage"),
    "AsciiHeader": ("um982py.messages.frames", "AsciiHeader"),
    "AsciiMessage": ("um982py.messages.frames", "AsciiMessage"),
    "BestNavigation": ("um982py.messages.navigation", "BestNavigation"),
    "BinaryHeader": ("um982py.messages.frames", "BinaryHeader"),
    "BinaryMessage": ("um982py.messages.frames", "BinaryMessage"),
    "CommandResponse": ("um982py.messages.frames", "CommandResponse"),
    "ErrorEllipse": ("um982py.precision", "ErrorEllipse"),
    "Fix": ("um982py.messages.navigation", "Fix"),
    "Heading": ("um982py.messages.navigation", "Heading"),
    "OemAsciiHeader": ("um982py.messages.frames", "OemAsciiHeader"),
    "OemBinaryHeader": ("um982py.messages.frames", "OemBinaryHeader"),
    "LogListMessage": ("um982py.messages.frames", "LogListMessage"),
    "Message": ("um982py.messages.frames", "Message"),
    "Observation": ("um982py.messages.observations", "Observation"),
    "Position": ("um982py.messages.navigation", "Position"),
    "PositionPrecision": ("um982py.precision", "PositionPrecision"),
    "PpsConfigInfo": ("um982py.messages.receiver_status", "PpsConfigInfo"),
    "PpsQuality": ("um982py.messages.receiver_status", "PpsQuality"),
    "PpsStatus": ("um982py.messages.receiver_status", "PpsStatus"),
    "Record": ("um982py.messages.record", "Record"),
    "RtcmMessage": ("um982py.messages.frames", "RtcmMessage"),
    "Sentence": ("um982py.messages.frames", "Sentence"),
    "SpoofInfo": ("um982py.messages.receiver_status", "SpoofInfo"),
    "SpoofNotice": ("um982py.messages.receiver_status", "SpoofNotice"),
    "SpoofSignal": ("um982py.messages.receiver_status", "SpoofSignal"),
    "SpoofTimeNotice": ("um982py.messages.receiver_status", "SpoofTimeNotice"),
    "TextLine": ("um982py.messages.frames", "TextLine"),
    "TrackingStatus": ("um982py.messages.observations", "TrackingStatus"),
    "Value": ("um982py.messages.record", "Value"),
    "Version": ("um982py.messages.version", "Version"),
    "decode_log": ("um982py.messages.decode", "decode_log"),
}

__all__ = [
    "AbbreviatedAsciiMessage",
    "AsciiHeader",
    "AsciiMessage",
    "BestNavigation",
    "BinaryHeader",
    "BinaryMessage",
    "CommandResponse",
    "ErrorEllipse",
    "Fix",
    "Heading",
    "LogListMessage",
    "Message",
    "Observation",
    "OemAsciiHeader",
    "OemBinaryHeader",
    "Position",
    "PositionPrecision",
    "PpsConfigInfo",
    "PpsQuality",
    "PpsStatus",
    "Record",
    "RtcmMessage",
    "Sentence",
    "SpoofInfo",
    "SpoofNotice",
    "SpoofSignal",
    "SpoofTimeNotice",
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
