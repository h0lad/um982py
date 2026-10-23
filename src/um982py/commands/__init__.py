"""Command builders and the documented log catalogue."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.commands import (
        assistance,
        configuration,
        logging,
        masking,
        modes,
        queries,
        system,
    )
    from um982py.commands.core import Command, action
    from um982py.commands.logs import Log
    from um982py.commands.types import (
        Constellation,
        NmeaVersion,
        Parity,
        Port,
        ResetTarget,
        RoverDynamics,
        Trigger,
    )

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "Command": ("um982py.commands.core", "Command"),
    "Constellation": ("um982py.commands.types", "Constellation"),
    "Log": ("um982py.commands.logs", "Log"),
    "NmeaVersion": ("um982py.commands.types", "NmeaVersion"),
    "Parity": ("um982py.commands.types", "Parity"),
    "Port": ("um982py.commands.types", "Port"),
    "ResetTarget": ("um982py.commands.types", "ResetTarget"),
    "RoverDynamics": ("um982py.commands.types", "RoverDynamics"),
    "Trigger": ("um982py.commands.types", "Trigger"),
    "action": ("um982py.commands.core", "action"),
    "assistance": ("um982py.commands.assistance", None),
    "configuration": ("um982py.commands.configuration", None),
    "logging": ("um982py.commands.logging", None),
    "masking": ("um982py.commands.masking", None),
    "modes": ("um982py.commands.modes", None),
    "queries": ("um982py.commands.queries", None),
    "system": ("um982py.commands.system", None),
}

__all__ = [
    "Command",
    "Constellation",
    "Log",
    "NmeaVersion",
    "Parity",
    "Port",
    "ResetTarget",
    "RoverDynamics",
    "Trigger",
    "action",
    "assistance",
    "configuration",
    "logging",
    "masking",
    "modes",
    "queries",
    "system",
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
