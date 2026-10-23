"""Log sequencing CONFIG command (UM982/UM982C only)."""

from typing import Literal

from um982py.commands.core import Command
from um982py.commands.validation import config, integer
from um982py.messages import CommandResponse


def log_sequence(order: Literal[1, 2] = 2) -> Command[CommandResponse]:
    return config("LOGSEQ", integer(order, 1, 2))
