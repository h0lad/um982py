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
from um982py.errors import UM982Error

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
    active_group: SignalGroup
    applied: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    saved: bool

    @property
    def changed(self) -> bool:
        """True only when the active signal group differs from the previous one."""
        return self.active_group != self.previous_group

    @property
    def complete(self) -> bool:
        """True only when no feature was refused."""
        return not self.rejected


def augmentation_plan(current: SignalGroup) -> tuple[AugmentationStep, ...]:
    """Commands that enable SBAS, E6-HAS, B2b-PPP and the remaining refinements.

    The signal group is only touched when it does not already track Galileo E6
    and BDS B2b, because changing it restarts acquisition.  Every other step is
    idempotent on the firmware, so it is always re-asserted.
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
    receiver: CommandExecutor, *, persist: bool = True
) -> AugmentationState:
    """Apply every augmentation feature and persist a signal-group change.

    A refused feature never aborts the session: it is reported in ``rejected``
    so a firmware without that option still yields a usable receiver.  The
    configuration is saved only when the signal group changed, so the receiver
    boots into the high-accuracy group from then on without a flash write per
    session.
    """
    previous = receiver.execute(current_signal_group())
    applied: list[str] = []
    rejected: list[tuple[str, str]] = []
    for step in augmentation_plan(previous):
        try:
            receiver.execute(step.command)
        except (UM982Error, OSError, ValueError) as error:
            rejected.append((step.feature, str(error)))
        else:
            applied.append(step.feature)
    try:
        active = receiver.execute(current_signal_group())
    except (UM982Error, OSError, ValueError) as error:
        rejected.append(("read_signal_group", str(error)))
        active = HIGH_ACCURACY_SIGNAL_GROUP if "signal_group" in applied else previous
    saved = False
    if active != previous and persist:
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
