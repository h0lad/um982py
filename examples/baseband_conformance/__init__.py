"""Records an ACK and reject matrix with a receiver state check."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from um982py.commands.core import Command
from um982py.experimental import (
    BasebandCommand,
    BasebandNotice,
    LogList,
    SideEffect,
    baseband_command,
)
from um982py.messages import CommandResponse

ACKNOWLEDGEMENTS = frozenset({"UART_CMD_OK", "SPI_CMD_OK"})
"""Notices the baseband prints when it accepts a forwarded command."""
REJECTIONS = frozenset(
    {
        "UART_CMD_FAIL",
        "SPI_CMD_FAIL",
        "RFSPIREAD_ERROR",
        "RFSPIWRITE",
        "RFSPIWRITE_PARSE_ERROR",
        "BBLOGEN_ERROR",
        "DUPLICATE_COMMAND",
    }
)
"""Notices the baseband prints when it rejects or cannot parse a command."""
SKIPPED_EFFECTS = frozenset({SideEffect.DESTRUCTIVE, SideEffect.UNVERIFIED})


class Verdict(StrEnum):
    """Outcome of one probed baseband command."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NO_REPORT = "no_report"


@dataclass(frozen=True, slots=True)
class ConformanceRow:
    """Verdict and side-effect class of one baseband command."""

    command: BasebandCommand
    side_effect: SideEffect
    verdict: Verdict
    notices: tuple[str, ...]
    application_ack: bool

    @property
    def probe_safe(self) -> bool:
        """True when the extended class leaves the command out of the skip set."""
        return self.side_effect not in SKIPPED_EFFECTS


@dataclass(frozen=True, slots=True)
class BasebandSnapshot:
    """Configuration, mode, masks and logs captured around a command."""

    configuration: tuple[bytes, ...]
    mode: tuple[str, ...]
    masks: tuple[tuple[str, ...], ...]
    logs: LogList

    @classmethod
    def from_parts(cls, parts: tuple[object, ...]) -> BasebandSnapshot:
        """Build a snapshot from the four values of ``receiver_state``."""
        configuration, mode, masks, logs = parts
        if not isinstance(logs, LogList):
            raise ValueError("the fourth state part is not a log list")
        return cls(
            configuration=cast("tuple[bytes, ...]", configuration),
            mode=cast("tuple[str, ...]", mode),
            masks=cast("tuple[tuple[str, ...], ...]", masks),
            logs=logs,
        )

    def difference(self, other: BasebandSnapshot) -> tuple[str, ...]:
        """Names of the parts that differ from another snapshot."""
        return tuple(
            name
            for name, left, right in (
                ("configuration", self.configuration, other.configuration),
                ("mode", self.mode, other.mode),
                ("masks", self.masks, other.masks),
                ("logs", self.logs, other.logs),
            )
            if left != right
        )


@dataclass(frozen=True, slots=True)
class StateCheck:
    """Snapshot comparison around one probed command."""

    command: BasebandCommand
    changed: tuple[str, ...]

    @property
    def identical(self) -> bool:
        """True when the command left the receiver state unchanged."""
        return not self.changed


def probe(command: BasebandCommand) -> Command[CommandResponse]:
    """BBCMD wrapper of the bare command name the matrix sends."""
    return baseband_command(command)


def verdict(command: BasebandCommand, notices: Sequence[BasebandNotice]) -> Verdict:
    """Classify the baseband notices of one command as accepted or rejected."""
    names = {notice.name for notice in notices}
    if names & REJECTIONS:
        return Verdict.REJECTED
    if names & ACKNOWLEDGEMENTS:
        return Verdict.ACCEPTED
    if command.notice in names:
        return Verdict.ACCEPTED
    return Verdict.NO_REPORT


def conformance_row(
    command: BasebandCommand,
    notices: Sequence[BasebandNotice],
    *,
    application_ack: bool = False,
) -> ConformanceRow:
    """Row of one command with its verdict and the notices it answered with."""
    selected = BasebandCommand(command)
    return ConformanceRow(
        command=selected,
        side_effect=selected.category,
        verdict=verdict(selected, notices),
        notices=tuple(sorted({notice.name for notice in notices})),
        application_ack=application_ack,
    )


def conformance_matrix(
    notices: Mapping[BasebandCommand, Sequence[BasebandNotice]],
    *,
    acknowledged: Sequence[BasebandCommand] = (),
) -> tuple[ConformanceRow, ...]:
    """One row per extended command, in catalogue order."""
    acked = frozenset(acknowledged)
    return tuple(
        conformance_row(
            command,
            notices.get(command, ()),
            application_ack=command in acked,
        )
        for command in BasebandCommand
    )


def probe_commands(*, include_destructive: bool = False) -> tuple[BasebandCommand, ...]:
    """Commands to probe, excluding disruptive and unverified classes by default."""
    return tuple(
        command
        for command in BasebandCommand
        if include_destructive or command.category not in SKIPPED_EFFECTS
    )


def state_check(
    command: BasebandCommand, before: BasebandSnapshot, after: BasebandSnapshot
) -> StateCheck:
    """Compare the snapshots taken before and after one probe."""
    return StateCheck(
        command=BasebandCommand(command), changed=before.difference(after)
    )


def all_restored(checks: Sequence[StateCheck]) -> bool:
    """True when every probe left the receiver state bit-identical."""
    return all(check.identical for check in checks)
