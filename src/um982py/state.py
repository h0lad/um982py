"""Snapshot and restore the receiver settings supported by this module."""

from dataclasses import dataclass, field
from typing import Literal

from um982py._receiver_state import receiver_state
from um982py.commands import logging, modes
from um982py.commands.configuration.corrections import (
    doppler_prediction,
    mmp,
    ppp_datum,
    rtk_assists_ppp,
)
from um982py.commands.types import RoverDynamics
from um982py.messages import Sentence
from um982py.protocol import StreamDecoder
from um982py.receiver import Receiver
from um982py.receiver_models import LogEntry


@dataclass(frozen=True, slots=True)
class RoverMode:
    """The rover dynamics and optional profile reported by the receiver."""

    dynamics: RoverDynamics
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class RestorableSettings:
    """The settings that can be restored from a receiver snapshot."""

    rover_mode: RoverMode | None
    ppp_datum: Literal["WGS84", "PPPORIGINAL"] | None
    mmp: bool | None
    doppler_prediction: bool | None
    rtk_assists_ppp: bool | None
    problems: tuple[str, ...] = ()

    @property
    def available(self) -> tuple[str, ...]:
        """Return the names of the settings whose values can be restored."""
        return (
            *(
                name
                for name, value in (
                    ("rover_mode", self.rover_mode),
                    ("ppp_datum", self.ppp_datum),
                    ("mmp", self.mmp),
                    ("doppler_prediction", self.doppler_prediction),
                    ("rtk_assists_ppp", self.rtk_assists_ppp),
                )
                if value is not None
            ),
            "subscriptions",
        )


@dataclass(frozen=True, slots=True)
class ReceiverState:
    """Configuration, mode, masks and output subscriptions at one instant."""

    configuration: tuple[bytes, ...]
    mode: tuple[str, ...]
    masks: tuple[tuple[str, ...], ...]
    logs: tuple[LogEntry, ...]
    settings: RestorableSettings = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _settings(self))

    def differences(self, other: "ReceiverState") -> tuple[str, ...]:
        """List fields that differ, ignoring output-subscription order."""
        return tuple(
            name
            for name, left, right in (
                ("configuration", self.configuration, other.configuration),
                ("mode", self.mode, other.mode),
                ("masks", self.masks, other.masks),
                ("logs", frozenset(self.logs), frozenset(other.logs)),
            )
            if left != right
        )


@dataclass(frozen=True, slots=True)
class StateRestoration:
    """Restoration errors and differences that remain after verification."""

    before: ReceiverState
    after: ReceiverState
    errors: tuple[str, ...]

    @property
    def differences(self) -> tuple[str, ...]:
        return self.before.differences(self.after)

    @property
    def restored(self) -> bool:
        return not self.errors and not self.differences


def snapshot_receiver_state(receiver: Receiver) -> ReceiverState:
    """Read configuration, mode, masks and the current log subscriptions."""
    configuration, mode, masks, logs = receiver_state(receiver)
    return ReceiverState(
        configuration,
        mode,
        masks,
        logs.entries,
    )


def _datum(state: ReceiverState) -> str | None:
    values = set()
    for raw in state.configuration:
        for message in StreamDecoder().feed(raw):
            if isinstance(message, Sentence) and len(message.fields) >= 2:
                parts = message.fields[1].split()
                if parts[:3] == ["CONFIG", "PPP", "DATUM"] and len(parts) == 4:
                    values.add(parts[3])
    if len(values) > 1:
        raise ValueError("receiver reports multiple PPP datums")
    return next(iter(values), None)


def _switch(state: ReceiverState, topic: str) -> bool | None:
    values = set()
    for raw in state.configuration:
        for message in StreamDecoder().feed(raw):
            if isinstance(message, Sentence) and len(message.fields) >= 2:
                parts = message.fields[1].split()
                if len(parts) == 3 and parts[:2] == ["CONFIG", topic]:
                    if parts[2] not in ("ENABLE", "DISABLE"):
                        raise ValueError(f"unsupported {topic} value {parts[2]}")
                    values.add(parts[2] == "ENABLE")
    if len(values) > 1:
        raise ValueError(f"receiver reports conflicting {topic} settings")
    return next(iter(values), None)


def _settings(state: ReceiverState) -> RestorableSettings:
    problems: list[str] = []
    mode = None
    try:
        parts = state.mode[0].split() if state.mode else []
        if len(parts) not in (3, 4) or parts[:2] != ["MODE", "ROVER"]:
            raise ValueError("unsupported receiver mode")
        profile = parts[3] if len(parts) == 4 else None
        dynamics = RoverDynamics(parts[2])
        modes.rover(dynamics, profile=profile)
        mode = RoverMode(dynamics, profile)
    except ValueError as error:
        problems.append(f"mode: {error}")
    datum: Literal["WGS84", "PPPORIGINAL"] | None = None
    try:
        raw_datum = _datum(state)
        if raw_datum == "WGS84":
            datum = "WGS84"
        elif raw_datum == "PPPORIGINAL":
            datum = "PPPORIGINAL"
        elif raw_datum is not None:
            raise ValueError(f"unsupported PPP datum {raw_datum}")
    except ValueError as error:
        problems.append(f"PPP datum: {error}")
    switches: list[bool | None] = []
    for topic in ("MMP", "PSRVELDRPOS", "RTKASITPPP"):
        try:
            switches.append(_switch(state, topic))
        except ValueError as error:
            switches.append(None)
            problems.append(f"{topic}: {error}")
    return RestorableSettings(
        mode, datum, switches[0], switches[1], switches[2], tuple(problems)
    )


def restore_receiver_state(
    receiver: Receiver, expected: ReceiverState
) -> StateRestoration:
    """Restore supported settings and report any remaining differences.

    The caller must restore any signal group and reconnect after a reboot first.
    Other configuration and masks are verified but are not sent back as commands.
    """
    current = snapshot_receiver_state(receiver)
    saved = expected.settings
    errors = [
        problem
        for problem in saved.problems
        if not problem.startswith("mode:") or current.mode != expected.mode
    ]
    if current.mode != expected.mode:
        try:
            if saved.rover_mode is not None:
                receiver.execute(
                    modes.rover(
                        saved.rover_mode.dynamics, profile=saved.rover_mode.profile
                    )
                )
        except Exception as error:
            errors.append(f"mode: {error}")
    current = snapshot_receiver_state(receiver)
    active = current.settings
    for topic, saved_value, active_value, factory in (
        ("MMP", saved.mmp, active.mmp, mmp),
        (
            "PSRVELDRPOS",
            saved.doppler_prediction,
            active.doppler_prediction,
            doppler_prediction,
        ),
        ("RTKASITPPP", saved.rtk_assists_ppp, active.rtk_assists_ppp, rtk_assists_ppp),
    ):
        try:
            if saved_value is not None and saved_value != active_value:
                if any(problem.startswith(f"{topic}:") for problem in active.problems):
                    raise ValueError("current setting could not be read")
                receiver.execute(factory(enabled=saved_value))
        except Exception as error:
            errors.append(f"{topic}: {error}")
    try:
        if saved.ppp_datum is not None and saved.ppp_datum != active.ppp_datum:
            if any(problem.startswith("PPP datum:") for problem in active.problems):
                raise ValueError("current datum could not be read")
            receiver.execute(ppp_datum(saved.ppp_datum))
    except Exception as error:
        errors.append(f"PPP datum: {error}")
    current = snapshot_receiver_state(receiver)
    # Stop only changed subscriptions before restoring the saved entries.
    expected_logs = set(expected.logs)
    current_logs = set(current.logs)
    for entry in current.logs:
        if entry not in expected_logs:
            try:
                receiver.execute(logging.stop(entry.name, port=entry.port))
            except Exception as error:
                errors.append(f"stop {entry.name} on {entry.port}: {error}")
    for entry in expected.logs:
        if entry not in current_logs:
            try:
                receiver.execute(entry.command())
            except Exception as error:
                errors.append(f"restore {entry.name} on {entry.port}: {error}")
    after = snapshot_receiver_state(receiver)
    return StateRestoration(expected, after, tuple(errors))
