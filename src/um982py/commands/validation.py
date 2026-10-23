"""Validates command arguments and renders them as text."""

from math import inf

from um982py.commands.core import Command, action, number
from um982py.messages import CommandResponse


def integer(value: int, minimum: int, maximum: int) -> str:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Expected an integer in {minimum}..{maximum}")
    return str(value)


def option(value: str, choices: tuple[str, ...]) -> str:
    value = value.upper()
    if value not in choices:
        raise ValueError(f"Expected one of {choices}")
    return value


def text(value: str, maximum: int = 255, *, quoted: bool = False) -> str:
    if not value or len(value) > maximum or any(not 32 <= ord(c) < 127 for c in value):
        raise ValueError("Invalid ASCII parameter")
    if any(c in value for c in '"*#;') or (
        not quoted and any(c.isspace() for c in value)
    ):
        raise ValueError("Parameter contains a command delimiter")
    return f'"{value}"' if quoted else value


def config(name: str, *parameters: str) -> Command[CommandResponse]:
    return action(" ".join(("CONFIG", name, *parameters)))


def switch(name: str, enabled: bool) -> Command[CommandResponse]:
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return config(name, "ENABLE" if enabled else "DISABLE")


def positive(value: float) -> str:
    return number(value, 0, inf)
