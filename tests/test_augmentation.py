"""Tests that every augmentation feature is asserted without failing the session."""

from __future__ import annotations

import pytest

from um982py.augmentation import (
    HIGH_ACCURACY_SIGNAL_GROUP,
    AugmentationState,
    augmentation_plan,
    enable_augmentation,
)
from um982py.commands.configuration import SignalGroup
from um982py.commands.core import Command
from um982py.errors import CommandRejected
from um982py.messages import CommandResponse

FEATURES = (
    "signal_group",
    "sbas",
    "ppp",
    "mmp",
    "anti_jam",
    "doppler_prediction",
    "rtk_assists_ppp",
)


class Scripted:
    """Answers like a receiver that may refuse selected commands."""

    def __init__(self, group: SignalGroup, refused: tuple[str, ...] = ()) -> None:
        self.group = group
        self.refused = refused
        self.commands: list[str] = []
        self.saved = False

    def execute[T](self, command: Command[T], *, timeout: float | None = None) -> T:
        del timeout
        text = command.text
        self.commands.append(text)
        if text == "CONFIG":
            return self.group  # type: ignore[return-value]
        for marker in self.refused:
            if marker in text:
                raise CommandRejected(text, "ERROR")
        if text.startswith("CONFIG SIGNALGROUP"):
            master, slave = (int(part) for part in text.split()[2:4])
            self.group = SignalGroup(master, slave)
        if text == "SAVECONFIG":
            self.saved = True
        return CommandResponse(command=text, status="OK", raw=b"")  # type: ignore[return-value]


def state(group: SignalGroup) -> AugmentationState:
    return enable_augmentation(Scripted(group))


def test_plan_only_switches_a_group_that_cannot_see_e6_or_b2b() -> None:
    old = augmentation_plan(SignalGroup(4, 5))
    assert old[0].feature == "signal_group"
    assert "CONFIG SIGNALGROUP 3 6" in old[0].command.text
    assert tuple(step.feature for step in old) == FEATURES
    new = augmentation_plan(HIGH_ACCURACY_SIGNAL_GROUP)
    assert "signal_group" not in {step.feature for step in new}
    assert tuple(step.feature for step in new) == FEATURES[1:]


def test_a_group_change_is_applied_and_saved_once() -> None:
    receiver = Scripted(SignalGroup(4, 5))
    result = enable_augmentation(receiver)
    assert result.previous_group == SignalGroup(4, 5)
    assert result.active_group == HIGH_ACCURACY_SIGNAL_GROUP
    assert result.applied == FEATURES
    assert result.changed and result.saved and result.complete
    assert receiver.commands.count("SAVECONFIG") == 1


def test_an_already_correct_group_is_not_rewritten_or_saved() -> None:
    receiver = Scripted(HIGH_ACCURACY_SIGNAL_GROUP)
    result = enable_augmentation(receiver)
    assert not result.changed and not result.saved
    assert "signal_group" not in result.applied
    assert "SAVECONFIG" not in receiver.commands
    assert result.complete


def test_persisting_can_be_disabled_without_losing_the_other_steps() -> None:
    receiver = Scripted(SignalGroup(4, 5))
    result = enable_augmentation(receiver, persist=False)
    assert result.changed and not result.saved
    assert "SAVECONFIG" not in receiver.commands
    assert result.applied == FEATURES


def test_a_refused_feature_does_not_block_the_remaining_features() -> None:
    result = enable_augmentation(Scripted(HIGH_ACCURACY_SIGNAL_GROUP, ("MMP",)))
    assert ("mmp", "CONFIG MMP ENABLE: ERROR") in result.rejected
    assert not result.complete
    assert {"sbas", "ppp", "anti_jam"} <= set(result.applied)


def test_a_refused_group_change_keeps_the_previous_group_unsaved() -> None:
    result = enable_augmentation(Scripted(SignalGroup(4, 5), ("SIGNALGROUP",)))
    assert result.active_group == SignalGroup(4, 5)
    assert not result.changed and not result.saved
    assert "signal_group" not in result.applied
    assert "sbas" in result.applied


def test_a_failed_save_is_reported_while_the_features_stay_active() -> None:
    result = enable_augmentation(Scripted(SignalGroup(4, 5), ("SAVECONFIG",)))
    assert result.changed and not result.saved
    assert ("save_configuration", "SAVECONFIG: ERROR") in result.rejected
    assert result.active_group == HIGH_ACCURACY_SIGNAL_GROUP


@pytest.mark.parametrize("group", [SignalGroup(4, 5), HIGH_ACCURACY_SIGNAL_GROUP])
def test_every_step_names_a_documented_command(group: SignalGroup) -> None:
    for step in augmentation_plan(group):
        assert step.command.text.startswith("CONFIG ")
        assert step.feature != ""
