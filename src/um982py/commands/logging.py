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
