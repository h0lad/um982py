"""Log request, output and stop commands."""

from um982py.commands.catalog import RTCM_LOGS, WIRE_LOGS
from um982py.commands.core import Command, action, number, token
from um982py.commands.types import Port, Trigger
from um982py.messages.frames import (
    AsciiMessage,
    BinaryMessage,
    CommandResponse,
    LogListMessage,
    Message,
    RtcmMessage,
    Sentence,
)


def interval_from_rate(rate_hz: float) -> float:
    """Convert a documented N4 output rate to the receiver's interval in seconds.

    The receiver, its firmware, signal group and log determine which rates are
    actually available. In particular, 50 Hz applies only to certain N4 models.
    """
    intervals: dict[float, float] = {
        1: 1.0,
        2: 0.5,
        5: 0.2,
        10: 0.1,
        20: 0.05,
        50: 0.02,
    }
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, (int, float)):
        raise ValueError("rate_hz must be one of 1, 2, 5, 10, 20 or 50 Hz")
    try:
        return intervals[rate_hz]
    except KeyError:
        raise ValueError(
            "rate_hz must be one of 1, 2, 5, 10, 20 or 50 Hz; "
            "100 Hz is not documented for N4 output"
        ) from None


def output_interval(interval: float | None, rate_hz: float | None) -> float:
    """Resolve mutually exclusive interval and rate options."""
    if interval is not None and rate_hz is not None:
        raise ValueError("specify interval or rate_hz, not both")
    return (
        interval_from_rate(rate_hz)
        if rate_hz is not None
        else (1.0 if interval is None else interval)
    )


def _text(name: str, interval: float | Trigger | None, port: Port | None) -> str:
    parts = [token(name)]
    if port is not None:
        parts.append(Port(port).value)
    if interval is not None:
        if isinstance(interval, Trigger):
            parts.append(interval.value)
        else:
            parts.append(number(interval, 0.001, 86400))
    return " ".join(parts)


def output(
    name: str, interval: float | Trigger, *, port: Port | None = None
) -> Command[CommandResponse]:
    return action(_text(name, interval, port))


def request(
    name: str, *, port: Port | None = None, message_id: int | None = None
) -> Command[Message]:
    name = token(name)
    if message_id is None and name in WIRE_LOGS:
        message_id = WIRE_LOGS[name].message_id

    def matches(message: Message) -> bool:
        if isinstance(message, RtcmMessage):
            return name in RTCM_LOGS and message.message_type == message_id
        if isinstance(message, LogListMessage):
            return name == "UNILOGLIST"
        if isinstance(message, BinaryMessage):
            return (
                name not in RTCM_LOGS
                and name.endswith("B")
                and message_id is not None
                and message.header.message_id == message_id
            )
        if isinstance(message, AsciiMessage):
            return message.name in (name, name.removesuffix("A"))
        if isinstance(message, Sentence):
            return message.name == name or (
                name.startswith("GP") and message.kind == name[2:]
            )
        return False

    if name.endswith("B") and message_id is None:
        raise ValueError("Binary requests require a message_id")
    return Command(_text(name, None, port), matches, lambda message: message)


def stop(
    name: str | None = None, *, port: Port | None = None
) -> Command[CommandResponse]:
    parts = ["UNLOG"]
    if port is not None:
        parts.append(Port(port).value)
    if name is not None:
        parts.append(token(name))
    return action(" ".join(parts))
