"""Save and reset commands."""

from um982py.commands.core import Command, action
from um982py.commands.types import ResetTarget
from um982py.messages.frames import CommandResponse


def save_configuration() -> Command[CommandResponse]:
    return action("SAVECONFIG")


def reset(*targets: ResetTarget) -> Command[CommandResponse]:
    return action(
        " ".join(("RESET", *(ResetTarget(target).value for target in targets)))
    )


def factory_reset() -> Command[CommandResponse]:
    return action("FRESET")
