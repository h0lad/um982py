"""Tests the baseband conformance matrix against ground truth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from examples.baseband_conformance import (
    BasebandSnapshot,
    Verdict,
    conformance_matrix,
    conformance_row,
    probe,
    probe_commands,
    verdict,
)
from examples.baseband_conformance import __main__ as cli
from examples.baseband_conformance.__main__ import main

from conftest import ReplayTransport, acknowledgement
from um982py.experimental import BasebandCommand, SideEffect, scan_notices
from um982py.experimental.models import LogList
from um982py.receiver import Receiver

EXTENDED_COMMANDS = 41
PROBE_SAFE_COMMANDS = 26
ACKNOWLEDGEMENT = scan_notices(b"$UartBinayCMDOK:\r\n")
FAILURE = scan_notices(b"$UartBinayCMDFAIL:\r\n")
TIMING_NOTICE = scan_notices(b"$Parse TimingMode: 1\r\n")
TRACK_NOTICE = scan_notices(b"$TrackMode,2\r\n")
RFSPI_READ_ERROR = scan_notices(b"$RFSPIRead:0000000001 can not parsed!\r\n")
RFSPI_WRITE_ERROR = scan_notices(b"$RFSPIWrite:0000000001 Address may not correct!\r\n")
RFSPI_WRITE_PARSE_ERROR = scan_notices(
    b"$RFSPIRead:0000000000000001x can not parsed!\r\n"
)
DUPLICATE = scan_notices(b"$ErrTrap:CmdDulDef:TIMINGMODE\r\n")


def test_a_generic_acknowledgement_accepts_the_command() -> None:
    assert verdict(BasebandCommand.TRACKMODE, ACKNOWLEDGEMENT) is Verdict.ACCEPTED


def test_a_generic_failure_rejects_the_command() -> None:
    assert verdict(BasebandCommand.TRACKMODE, FAILURE) is Verdict.REJECTED


def test_a_notice_family_accepts_only_its_own_command() -> None:
    assert verdict(BasebandCommand.TIMINGMODE, TIMING_NOTICE) is Verdict.ACCEPTED
    assert verdict(BasebandCommand.TRACKMODE, TIMING_NOTICE) is Verdict.NO_REPORT
    assert verdict(BasebandCommand.TRACKMODE, TRACK_NOTICE) is Verdict.ACCEPTED


def test_a_parse_error_rejects_host_read_and_write() -> None:
    assert verdict(BasebandCommand.RFSPIREAD, RFSPI_READ_ERROR) is Verdict.REJECTED
    assert verdict(BasebandCommand.RFSPIWRITE, RFSPI_WRITE_ERROR) is Verdict.REJECTED
    assert (
        verdict(BasebandCommand.RFSPIWRITE, RFSPI_WRITE_PARSE_ERROR) is Verdict.REJECTED
    )


def test_a_duplicate_command_notice_rejects_the_command() -> None:
    assert verdict(BasebandCommand.TIMINGMODE, DUPLICATE) is Verdict.REJECTED


def test_a_rejection_outranks_a_family_notice() -> None:
    both = (*TIMING_NOTICE, *FAILURE)
    assert verdict(BasebandCommand.TIMINGMODE, both) is Verdict.REJECTED


def test_silence_is_reported_as_no_report() -> None:
    assert verdict(BasebandCommand.TIMINGMODE, ()) is Verdict.NO_REPORT


def test_the_verdict_is_reproducible_under_reordering() -> None:
    first = conformance_row(BasebandCommand.TIMINGMODE, (*TIMING_NOTICE, *FAILURE))
    second = conformance_row(
        BasebandCommand.TIMINGMODE, (*FAILURE, *TIMING_NOTICE, *TIMING_NOTICE)
    )
    assert first == second
    assert first.notices == ("TIMINGMODE", "UART_CMD_FAIL")


def test_the_matrix_covers_every_extended_command_in_catalogue_order() -> None:
    rows = conformance_matrix({})
    assert len(rows) == EXTENDED_COMMANDS
    assert tuple(row.command for row in rows) == tuple(BasebandCommand)
    assert all(row.side_effect is row.command.category for row in rows)
    assert all(row.verdict is Verdict.NO_REPORT for row in rows)


def test_the_matrix_records_the_application_acknowledgement() -> None:
    rows = conformance_matrix(
        {}, acknowledged=(BasebandCommand.TRACKMODE, BasebandCommand.TRACKMODE)
    )
    acked = [row.command for row in rows if row.application_ack]
    assert acked == [BasebandCommand.TRACKMODE]


def test_probing_skips_the_destructive_classes_by_default() -> None:
    safe = probe_commands()
    assert len(safe) == PROBE_SAFE_COMMANDS
    assert all(command.category is not SideEffect.DESTRUCTIVE for command in safe)
    assert len(probe_commands(include_destructive=True)) == EXTENDED_COMMANDS


def test_the_probe_wraps_the_bare_command_in_bbcmd() -> None:
    assert probe(BasebandCommand.RFSPIREAD).text == "BBCMD $RFSPIREAD"


def test_main_classifies_every_command_of_the_injected_matrix(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "matrix.json"
    assert main(["--json", str(destination)]) == 0
    payload = json.loads(destination.read_text())
    assert [row["verdict"] for row in payload["accepted"]] == ["accepted"] * (
        EXTENDED_COMMANDS
    )
    assert [row["verdict"] for row in payload["rejected"]] == ["rejected"] * (
        EXTENDED_COMMANDS
    )
    assert payload["restore"] is None


def test_main_attributes_captured_notices_by_family(tmp_path: Path) -> None:
    capture = tmp_path / "notices.bin"
    capture.write_bytes(
        b"$Parse TimingMode: 1\r\n"
        b"$UartBinayCMDFAIL:\r\n"
        b"$ErrTrap:CmdDulDef:TRACKMODE\r\n"
    )
    destination = tmp_path / "replay.json"
    assert main(["--replay", str(capture), "--json", str(destination)]) == 0
    payload = json.loads(destination.read_text())
    verdicts = {
        row["command"]: row["verdict"]
        for row in payload["rows"]
        if row["verdict"] != Verdict.NO_REPORT.value
    }
    assert verdicts == {"TIMINGMODE": "accepted"}
    assert payload["unattributed"] == ["DUPLICATE_COMMAND", "UART_CMD_FAIL"]
    assert payload["restore"] is None


class ClockTransport(ReplayTransport):
    def __init__(
        self, clock: list[float], responses: dict[bytes, bytes] | None = None
    ) -> None:
        super().__init__(responses, chunk=65536)
        self.clock = clock

    def read(self, size: int, timeout: float) -> bytes:
        if not self.pending:
            self.clock[0] += timeout
        return super().read(size, timeout)


def clocked_receiver(
    monkeypatch: pytest.MonkeyPatch, transport: ClockTransport
) -> None:
    monkeypatch.setattr(cli, "monotonic", lambda: transport.clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: transport.clock[0])
    monkeypatch.setattr(
        cli, "open_receiver", lambda args: Receiver(transport, timeout=args.timeout)
    )


def test_silent_receiver_fails_initial_state_promptly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = [0.0]
    transport = ClockTransport(clock)
    clocked_receiver(monkeypatch, transport)
    destination = tmp_path / "partial.json"
    assert (
        main(
            [
                "--port",
                "fake",
                "--timeout",
                "0.25",
                "--duration",
                "2",
                "--json",
                str(destination),
            ]
        )
        == 1
    )
    assert clock[0] == pytest.approx(0.25)
    assert transport.writes == [b"CONFIG\r\n"]
    assert transport.closed
    result = json.loads(destination.read_text())
    assert result["complete"] is False
    assert "CONFIG" in result["stopped_reason"]
    assert "Reading initial receiver state" in capsys.readouterr().err


def test_probe_keeps_notices_read_with_the_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    command = probe(BasebandCommand.TRACKMODE)
    transport = ClockTransport(
        clock, {command.encode(): acknowledgement(command.text) + b"$TrackMode,2\r\n"}
    )
    clocked_receiver(monkeypatch, transport)
    receiver = Receiver(transport)
    row = cli._probe(
        argparse.Namespace(window_seconds=0.2), receiver, BasebandCommand.TRACKMODE, 1.0
    )
    assert row.verdict is Verdict.ACCEPTED
    assert row.notices == ("TRACKMODE",)
    assert row.application_ack
    assert receiver.transport is transport
    assert clock[0] == pytest.approx(0.2)


def test_rf_probe_sends_validated_read_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from um982py.experimental import rf_spi_read

    clock = [0.0]
    request = rf_spi_read(0)
    transport = ClockTransport(clock, {request.encode(): acknowledgement(request.text)})
    clocked_receiver(monkeypatch, transport)
    receiver = Receiver(transport)
    row = cli._probe(
        argparse.Namespace(window_seconds=0.2, rf_address=0),
        receiver,
        BasebandCommand.RFSPIREAD,
        1.0,
    )
    assert transport.writes == [request.encode()]
    assert row.application_ack
    assert receiver.transport is transport


def test_total_duration_stops_scan_and_writes_partial_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = [0.0]
    commands = (
        BasebandCommand.TRACKMODE,
        BasebandCommand.TIMINGMODE,
        BasebandCommand.ACQFREQ,
    )
    transport = ClockTransport(
        clock,
        {
            probe(command).encode(): acknowledgement(probe(command).text)
            for command in commands
        },
    )
    clocked_receiver(monkeypatch, transport)
    state = BasebandSnapshot((), (), (), LogList(()))
    monkeypatch.setattr(cli, "_snapshot", lambda receiver, deadline: state)
    destination = tmp_path / "partial.json"
    options = [
        "--port",
        "fake",
        "--duration",
        "1",
        "--window-seconds",
        "0.6",
        "--json",
        str(destination),
    ]
    for command in commands:
        options.extend(("--command", command.value))
    assert main(options) == 1
    assert clock[0] == pytest.approx(1.0)
    result = json.loads(destination.read_text())
    assert result["complete"] is False
    assert len(result["rows"]) == 2
    assert result["remaining_commands"] == [commands[-1].value]
    assert transport.closed


def test_interrupt_saves_partial_output_and_closes_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class InterruptedTransport(ClockTransport):
        def write(self, data: bytes, timeout: float) -> None:
            raise KeyboardInterrupt

    transport = InterruptedTransport([0.0])
    clocked_receiver(monkeypatch, transport)
    state = BasebandSnapshot((), (), (), LogList(()))
    monkeypatch.setattr(cli, "_snapshot", lambda receiver, deadline: state)
    destination = tmp_path / "partial.json"
    assert (
        main(["--port", "fake", "--command", "TRACKMODE", "--json", str(destination)])
        == 130
    )
    assert transport.closed
    assert json.loads(destination.read_text())["stopped_reason"] == "interrupted"


def test_missing_baseband_reply_is_reported_as_insufficient_data() -> None:
    row = conformance_row(BasebandCommand.RFSPIREAD, (), application_ack=True)
    result = cli.payload((row,), (), source="live")
    assert result["status"] == "insufficient_data"
    assert result["rows"][0]["application_ack"] is True
