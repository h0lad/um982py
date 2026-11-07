"""Commands for enabling receiver augmentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from um982py.commands.configuration import (
    SignalGroup,
    anti_jam,
    current_signal_group,
    doppler_prediction,
    mmp,
    ppp,
    rtk_assists_ppp,
    sbas,
    signal_group,
)
from um982py.commands.core import Command
from um982py.commands.system import save_configuration
from um982py.errors import CommandRejected, UM982Error

if TYPE_CHECKING:
    from um982py.messages import CommandResponse

__all__ = [
    "HIGH_ACCURACY_SIGNAL_GROUP",
    "AugmentationState",
    "AugmentationStep",
    "CommandExecutor",
    "augmentation_plan",
    "enable_augmentation",
]

HIGH_ACCURACY_SIGNAL_GROUP = SignalGroup(3, 6)
"""Master group 3 tracks E6-HAS and B2b-PPP while slave group 6 keeps 20 Hz."""


class CommandExecutor(Protocol):
    """Executes one command, matching :meth:`um982py.Receiver.execute`."""

    def execute[T](self, command: Command[T], *, timeout: float | None = None) -> T: ...


@dataclass(frozen=True, slots=True)
class AugmentationStep:
    """One augmentation feature and the command that enables it."""

    feature: str
    command: Command[CommandResponse]


@dataclass(frozen=True, slots=True)
class AugmentationState:
    """What one session applied, what the firmware refused and what was saved."""

    previous_group: SignalGroup
    active_group: SignalGroup | None
    applied: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    saved: bool

    @property
    def changed(self) -> bool | None:
        """Whether the verified group changed, or None if it could not be read."""
        if self.active_group is None:
            return None
        return self.active_group != self.previous_group

    @property
    def complete(self) -> bool:
        """True when the plan, signal-group check and requested save succeeded."""
        return not self.rejected


def augmentation_plan(current: SignalGroup) -> tuple[AugmentationStep, ...]:
    """Commands that enable SBAS, E6-HAS, B2b-PPP and the remaining refinements.

    Switching to signal group 3/6 restarts acquisition, so the plan changes
    groups only when another group is active. The remaining settings are
    idempotent and are reasserted on each run.
    """
    steps: list[AugmentationStep] = []
    if current != HIGH_ACCURACY_SIGNAL_GROUP:
        steps.append(
            AugmentationStep(
                "signal_group",
                signal_group(
                    HIGH_ACCURACY_SIGNAL_GROUP.master,
                    HIGH_ACCURACY_SIGNAL_GROUP.slave,
                ),
            )
        )
    steps.extend(
        (
            AugmentationStep("sbas", sbas(enabled=True, service="AUTO")),
            AugmentationStep("ppp", ppp(enabled=True, service="AUTO")),
            AugmentationStep("mmp", mmp(enabled=True)),
            AugmentationStep("anti_jam", anti_jam("AUTO")),
            AugmentationStep("doppler_prediction", doppler_prediction(enabled=True)),
            AugmentationStep("rtk_assists_ppp", rtk_assists_ppp(enabled=True)),
        )
    )
    return tuple(steps)


def enable_augmentation(
    receiver: CommandExecutor, *, persist: bool = False
) -> AugmentationState:
    """Apply augmentation features, optionally saving a verified group change.

    Rejected commands are recorded and the remaining features are attempted.
    A transport or response failure stops the plan, but earlier changes may
    already be active. The configuration is saved only when requested and the
    signal-group readback confirms the change.
    """
    previous = receiver.execute(current_signal_group())
    applied: list[str] = []
    rejected: list[tuple[str, str]] = []
    for step in augmentation_plan(previous):
        try:
            receiver.execute(step.command)
        except CommandRejected as error:
            rejected.append((step.feature, str(error)))
        else:
            applied.append(step.feature)
    try:
        active = receiver.execute(current_signal_group())
    except (UM982Error, OSError, ValueError) as error:
        rejected.append(("read_signal_group", str(error)))
        active = None
    if (
        active is not None
        and active != HIGH_ACCURACY_SIGNAL_GROUP
        and "signal_group" in applied
    ):
        rejected.append(("verify_signal_group", "receiver reports a different group"))
    saved = False
    if active == HIGH_ACCURACY_SIGNAL_GROUP and active != previous and persist:
        try:
            receiver.execute(save_configuration())
        except (UM982Error, OSError, ValueError) as error:
            rejected.append(("save_configuration", str(error)))
        else:
            saved = True
    return AugmentationState(
        previous_group=previous,
        active_group=active,
        applied=tuple(applied),
        rejected=tuple(rejected),
        saved=saved,
    )
