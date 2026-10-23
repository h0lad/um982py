"""Receiver state restoration and verification."""

from unittest.mock import MagicMock, patch

from um982py.commands.types import Port, Trigger
from um982py.experimental.models import LogEntry
from um982py.protocol.checksums import nmea_checksum
from um982py.state import ReceiverState, restore_receiver_state


def config(datum: str) -> bytes:
    body = f"CONFIG,PPP,CONFIG PPP DATUM {datum}".encode()
    return b"$" + body + f"*{nmea_checksum(b'$' + body):02X}\r\n".encode()


def state(
    datum: str = "WGS84",
    mode: str = "MODE ROVER SURVEY",
    logs: tuple[LogEntry, ...] = (),
) -> ReceiverState:
    return ReceiverState((config(datum),), (mode, ""), (), logs)


def test_restores_mode_datum_and_changed_subscriptions() -> None:
    saved = LogEntry("RANGEB", Port.COM1, 1.0)
    extra = LogEntry("BESTXYZB", Port.COM1, Trigger.ON_CHANGED)
    expected = state(logs=(saved,))
    current = state("PPPORIGINAL", "MODE ROVER UAV", (extra,))
    receiver = MagicMock()
    with patch(
        "um982py.state.snapshot_receiver_state",
        side_effect=[current, current, current, expected],
    ):
        result = restore_receiver_state(receiver, expected)
    assert result.restored
    assert [call.args[0].text for call in receiver.execute.call_args_list] == [
        "MODE ROVER SURVEY",
        "CONFIG PPP DATUM WGS84",
        "UNLOG COM1 BESTXYZB",
        "RANGEB COM1 1",
    ]


def test_unhandled_configuration_change_is_reported_without_replaying_it() -> None:
    expected = state()
    current = ReceiverState(
        (*expected.configuration, b"unknown"), expected.mode, (), ()
    )
    receiver = MagicMock()
    with patch("um982py.state.snapshot_receiver_state", return_value=current):
        result = restore_receiver_state(receiver, expected)
    assert not result.restored
    assert result.differences == ("configuration",)
    receiver.execute.assert_not_called()


def test_restore_continues_after_command_failure_and_reports_it() -> None:
    saved = LogEntry("RANGEB", Port.COM1, 1.0)
    expected = state(logs=(saved,))
    current = state("PPPORIGINAL", "MODE ROVER UAV")
    receiver = MagicMock()
    receiver.execute.side_effect = [OSError("mode rejected"), None, None]
    with patch(
        "um982py.state.snapshot_receiver_state",
        side_effect=[current, current, current, expected],
    ):
        result = restore_receiver_state(receiver, expected)
    assert not result.restored
    assert result.errors == ("mode: mode rejected",)
    assert [call.args[0].text for call in receiver.execute.call_args_list] == [
        "MODE ROVER SURVEY",
        "CONFIG PPP DATUM WGS84",
        "RANGEB COM1 1",
    ]


def test_changed_interval_is_stopped_before_original_is_reinstalled() -> None:
    original = LogEntry("RANGEB", Port.COM1, 1.0)
    changed = LogEntry("RANGEB", Port.COM1, 5.0)
    expected = state(logs=(original,))
    current = state(logs=(changed,))
    receiver = MagicMock()
    with patch(
        "um982py.state.snapshot_receiver_state",
        side_effect=[current, current, current, expected],
    ):
        result = restore_receiver_state(receiver, expected)
    assert result.restored
    assert [call.args[0].text for call in receiver.execute.call_args_list] == [
        "UNLOG COM1 RANGEB",
        "RANGEB COM1 1",
    ]


def test_unknown_mode_is_not_sent_and_remains_a_difference() -> None:
    expected = state(mode="MODE UNKNOWN")
    current = state()
    receiver = MagicMock()
    with patch("um982py.state.snapshot_receiver_state", return_value=current):
        result = restore_receiver_state(receiver, expected)
    assert result.differences == ("mode",)
    assert result.errors == ("mode: unsupported receiver mode",)
    receiver.execute.assert_not_called()


def test_restores_documented_switches_lost_during_reboot() -> None:
    def switch(topic: str) -> bytes:
        body = f"CONFIG,{topic},CONFIG {topic} ENABLE".encode()
        return b"$" + body + f"*{nmea_checksum(b'$' + body):02X}\r\n".encode()

    current = state()
    expected = ReceiverState(
        current.configuration
        + tuple(switch(topic) for topic in ("MMP", "PSRVELDRPOS", "RTKASITPPP")),
        current.mode,
        current.masks,
        current.logs,
    )
    receiver = MagicMock()
    with patch(
        "um982py.state.snapshot_receiver_state",
        side_effect=[current, current, expected, expected],
    ):
        result = restore_receiver_state(receiver, expected)
    assert result.restored
    assert [call.args[0].text for call in receiver.execute.call_args_list] == [
        "CONFIG MMP ENABLE",
        "CONFIG PSRVELDRPOS ENABLE",
        "CONFIG RTKASITPPP ENABLE",
    ]


def test_snapshot_exposes_typed_values_and_restoration_capabilities() -> None:
    snapshot = state(logs=(LogEntry("RANGEB", Port.COM1, 1.0),))
    assert snapshot.settings.rover_mode is not None
    assert snapshot.settings.rover_mode.dynamics.value == "SURVEY"
    assert snapshot.settings.ppp_datum == "WGS84"
    assert snapshot.settings.mmp is None
    assert snapshot.settings.available == ("rover_mode", "ppp_datum", "subscriptions")
    assert snapshot.settings.problems == ()


def test_snapshot_reports_an_unsupported_mode_without_assuming_a_replacement() -> None:
    snapshot = state(mode="MODE BASE")
    assert snapshot.settings.rover_mode is None
    assert snapshot.settings.problems == ("mode: unsupported receiver mode",)
    assert "rover_mode" not in snapshot.settings.available
