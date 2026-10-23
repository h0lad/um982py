"""Restore only the output subscriptions changed by a bounded operation."""

from collections.abc import Iterator
from contextlib import contextmanager

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port
from um982py.messages import CommandResponse
from um982py.receiver import Receiver
from um982py.receiver_queries import log_list


@contextmanager
def temporary_subscriptions(
    receiver: Receiver, *planned: tuple[str, Command[CommandResponse]]
) -> Iterator[None]:
    """Install output temporarily, also cleaning up rejected/partial starts."""
    existing = receiver.execute(log_list()).entries
    started: list[tuple[str, Port | None]] = []
    try:
        for name, command in planned:
            parts = command.text.split()
            port = Port(parts[1]) if len(parts) == 3 else None
            # A failed command may still have changed the receiver's output state.
            started.append((name, port))
            receiver.execute(command)
        yield
    finally:
        errors: list[Exception] = []
        for name, port in reversed(tuple(dict.fromkeys(started))):
            try:
                receiver.execute(logging.stop(name, port=port))
            except Exception as error:
                errors.append(error)
            for entry in existing:
                if entry.name == name and (port is None or entry.port == port):
                    try:
                        receiver.execute(entry.command())
                    except Exception as error:
                        errors.append(error)
        if errors:
            raise ExceptionGroup("Could not restore temporary subscriptions", errors)
