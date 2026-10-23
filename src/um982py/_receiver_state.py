"""Read receiver configuration, mode, masks and output subscriptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from um982py.commands import queries
from um982py.errors import ProtocolError
from um982py.messages.frames import AsciiMessage, Message, Sentence
from um982py.receiver_models import LogList
from um982py.receiver_queries import log_list

if TYPE_CHECKING:
    from um982py.receiver import Receiver


def ascii_fields(message: Message) -> tuple[str, ...]:
    """Return the fields of an ASCII response, rejecting any other frame type."""
    if isinstance(message, (AsciiMessage, Sentence)):
        return message.fields
    raise ProtocolError(f"Expected an ASCII response, got {type(message).__name__}")


def ordered_log_list(receiver: Receiver) -> LogList:
    """Read active subscriptions ordered by name because LOGLISTA order varies."""
    entries = receiver.execute(log_list()).entries
    ordered = tuple(sorted(entries, key=lambda entry: entry.name))
    return LogList(ordered)


def receiver_state(
    receiver: Receiver,
) -> tuple[tuple[bytes, ...], tuple[str, ...], tuple[tuple[str, ...], ...], LogList]:
    """Read the receiver settings used when checking for changes."""
    return (
        tuple(
            sorted(
                {message.raw for message in receiver.collect(queries.configuration())}
            )
        ),
        ascii_fields(receiver.execute(queries.mode())),
        tuple(
            sorted(
                {ascii_fields(message) for message in receiver.collect(queries.masks())}
            )
        ),
        ordered_log_list(receiver),
    )
