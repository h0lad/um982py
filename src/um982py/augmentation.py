"""Commands for enabling receiver augmentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from um982py.commands.configuration import (
    SignalGroup,
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
"""Master group 3 tracks E6-HAS and B2b-PPP; rates depend on firmware and log."""


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
    """The settings applied, refused, and saved during one session."""

    previous_group: SignalGroup
    active_group: SignalGroup | None
    applied: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    saved: bool

    @property
    def changed(self) -> bool | None:
        """Whether the verified group changed, or None when readback failed."""
        if self.active_group is None:
            return None
        return self.active_group != self.previous_group

    @property
    def complete(self) -> bool:
        """True when the plan, signal-group check and requested save succeeded."""
        return not self.rejected


def augmentation_plan(
    current: SignalGroup, *, sbas_service: str = "AUTO"
) -> tuple[AugmentationStep, ...]:
    """Build the commands that enable SBAS, E6-HAS, B2b-PPP, and other refinements.

    A switch to signal group 3/6 restarts acquisition. The plan changes groups
    only if the receiver uses another group. Each run reapplies the remaining
    settings, which are idempotent.
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
            AugmentationStep("sbas", sbas(enabled=True, service=sbas_service)),
            AugmentationStep("ppp", ppp(enabled=True, service="AUTO")),
            AugmentationStep("mmp", mmp(enabled=True)),
            AugmentationStep(
                "disable_doppler_prediction", doppler_prediction(enabled=False)
            ),
            AugmentationStep("rtk_assists_ppp", rtk_assists_ppp(enabled=True)),
        )
    )
    return tuple(steps)


def enable_augmentation(
    receiver: CommandExecutor, *, persist: bool = False, sbas_service: str = "AUTO"
) -> AugmentationState:
    """Apply augmentation features, optionally saving the configuration.

    Command rejections appear in the report without stopping later features.
    A transport or response failure stops execution; earlier changes may remain
    active. Saving requires every command to succeed and the signal-group
    readback to match. Prediction may remain active if disabling it is rejected.
    """
    sbas(enabled=True, service=sbas_service)
    previous = receiver.execute(current_signal_group())
    applied: list[str] = []
    rejected: list[tuple[str, str]] = []
    for step in augmentation_plan(previous, sbas_service=sbas_service):
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
    if active is not None and active != HIGH_ACCURACY_SIGNAL_GROUP:
        rejected.append(("verify_signal_group", "receiver reports a different group"))
    saved = False
    if active == HIGH_ACCURACY_SIGNAL_GROUP and persist and not rejected:
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
