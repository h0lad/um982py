"""Tests the baseband command surface on live hardware."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from time import monotonic

import pytest

from um982py import Receiver
from um982py.commands import configuration, queries
from um982py.commands.core import action
from um982py.commands.types import Port, Trigger
from um982py.errors import CommandRejected, ResponseTimeout
from um982py.experimental import (
    BASEBAND_MESSAGE_CATALOGUE,
    BasebandCommand,
    BasebandSolution,
    DebugOutput,
    RawDataLog,
    capture_baseband,
    capture_baseband_notices,
    log_list,
    rf_spi_read,
    solution_jump_m,
    spec,
)
from um982py.experimental.capture import ordered_log_list
from um982py.messages import CommandResponse, Sentence

pytestmark = pytest.mark.hardware

#: Read-only commands that can be sent to a live receiver.
SAFE_QUERIES = (("RFSPIREAD", rf_spi_read(0)),)

#: Do not sweep these on a live receiver because values cannot be queried or restored.
NOT_SWEPT = (
    "AGNSSINFO",
    "RESET",
    "FRESET",
    "HOTSTART",
    "FORCEERRORTRAP",
    "ONESATTRK",
    "CUSTOMMODE",
    "RCVRUNNINGMODE",
    "CFGWNKROR",
    "TIMINGMODE",
    "TRACKMODE",
    "ACQFREQ",
    "SIGNALMASK",
    "SIGNALGROUP",
    "EVENTCONFIG",
    "AIENA",
    "PPPEN",
    "PPPRTKEN",
    "RECINFOEN",
    "RTCSTATUSEN",
    "JAMSTATUSEN",
    "ADRRELIABLITY",
    "ADRINITIAL",
    "MMPEN",
    "SBASCONTROL",
    "RFSPIWRITE",
    "RFCONFIG",
    "ANTISPOOFENA",
    "AICONFIG",
    "MODE",
    "AGNSSCONFIG",
    "SATMASK",
    "TCXOJUMPEN",
    "DCRMSGEN",
    "LEAPSECOND",
    "AEEN",
    "BBLOGEN",
    "LOG",
    "BBMSG2AP",
    "PPSCONFIG",
)


def snapshot(receiver: Receiver) -> dict[str, object]:
    return {
        "configuration": sorted(
            message.raw.decode("latin1").strip()
            for message in receiver.collect(queries.configuration())
        ),
        "mode": receiver.execute(queries.mode()).fields,
        "masks": tuple(m.fields for m in receiver.collect(queries.masks())),
        "logs": asdict(ordered_log_list(receiver)),
    }


@pytest.fixture(scope="module")
def baseband_receiver(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Receiver, dict[str, object]]]:
    port = request.config.getoption("--hardware-port")
    baud = request.config.getoption("--hardware-baud")
    report: dict[str, object] = {"port": port, "baud": baud}
    with Receiver.connect(port, baud, timeout=5) as device:
        before = snapshot(device)
        report["version"] = asdict(device.version())
        report["command_catalogue_size"] = len(BasebandCommand)
        report["not_swept_live"] = list(NOT_SWEPT)
        try:
            yield device, report
        finally:
            after = snapshot(device)
            report["state_restored"] = before == after
            report["decoder_errors"] = [str(e) for e in device.decoder.errors]
            report_path = Path(request.config.getoption("--hardware-report")).with_name(
                "baseband-pytest-validation.json"
            )
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            assert after == before
            assert not device.decoder.errors


def test_baseband_query_commands_acknowledged(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    results = []
    for _name, command in SAFE_QUERIES:
        response = device.execute(command)
        assert isinstance(response, CommandResponse)
        assert response.accepted
        assert command.matches(response)
        assert command.decode(response) is response
        results.append({"command": command.text, "status": response.status})
    report["baseband_queries"] = results


def test_baseband_command_catalogue_is_internal_and_complete(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    del device
    assert len(BasebandCommand) == 41
    for name, _ in SAFE_QUERIES:
        assert BasebandCommand[name].category == "QUERY"
    report["catalogue"] = [
        {"name": command.name, "category": command.category}
        for command in BasebandCommand
    ]


def test_receiver_streams_after_baseband_queries(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    deadline = monotonic() + 3
    sentences = 0
    while monotonic() < deadline:
        try:
            message = device.receive(timeout=min(1, deadline - monotonic()))
        except ResponseTimeout:
            continue
        if isinstance(message, Sentence):
            sentences += 1
    assert sentences > 0
    report["nmea_sentences_after_queries"] = sentences


@pytest.mark.parametrize("interval", [1, Trigger.ON_CHANGED])
def test_capture_baseband_is_state_restoring(
    baseband_receiver: tuple[Receiver, dict[str, object]],
    interval: float | Trigger,
) -> None:
    device, report = baseband_receiver
    capture = capture_baseband(
        device,
        RawDataLog.BASEBAND_PACKAGES,
        seconds=2,
        interval=interval,
        port=Port.COM1,
    )
    assert capture.cleanup_errors == ()
    assert capture.state_restored
    assert capture.acknowledged is True
    assert isinstance(capture.subscription_registered, bool)
    assert capture.manifest()["nmea_sentences"] > 0
    assert not capture.gate_command_sent
    report[f"capture_baseband_{interval}"] = capture.manifest()


def test_raw_error_without_colon_is_rejected_without_timeout(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    results = []
    for command in ("RAWDATAB RANGEB 1", "RAWDATAA RANGEA 1"):
        with pytest.raises(CommandRejected) as caught:
            device.execute(action(command))
        assert caught.value.response == "can't found device (null)"
        assert not device.decoder.errors
        results.append({"command": command, "status": caught.value.response})
    report["missing_colon_rejections"] = results


def test_live_baseband_notice_delivery(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    # Limit the diagnostic capture and disable the gate afterward.
    capture = capture_baseband_notices(device, seconds=4, enable_gate=True)
    assert capture.acknowledged and capture.subscription_registered
    assert (
        capture.command == DebugOutput.BASEBAND_NOTICE.on_changed(port=Port.COM1).text
    )
    assert capture.gate_command_sent
    assert capture.state_restored and not capture.cleanup_errors
    assert capture.manifest()["normal_decoder_errors"] == []
    headers = [n.decode() for n in capture.notices if n.name == "BBNOTICE"]
    assert len(headers) >= 2
    assert any(n.name in ("NAVPOS", "NAVVEL") for n in capture.notices)
    assert len({h.integer("tag_count") for h in headers}) >= 2
    assert all(
        h.integer("total_length") == h.integer("string_size") + 12 for h in headers
    )
    report["live_baseband_notices"] = capture.manifest()


def test_live_navpos_solutions_agree_with_printed_ecef(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    capture = capture_baseband_notices(device, seconds=4, enable_gate=True)
    assert capture.state_restored and not capture.cleanup_errors
    solutions = [
        BasebandSolution.from_record(notice.decode())
        for notice in capture.notices
        if notice.name == "NAVPOS"
    ]
    assert solutions
    assert all(solution.ecef_residual_m < 1.0 for solution in solutions)
    jumps = [
        solution_jump_m(previous, current) for previous, current in pairwise(solutions)
    ]
    assert all(jump >= 0.0 for jump in jumps)
    report["live_navpos_solutions"] = {
        "count": len(solutions),
        "worst_residual_m": max(solution.ecef_residual_m for solution in solutions),
        "worst_jump_m": max(jumps) if jumps else 0.0,
    }


def test_read_signal_group(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    group = device.execute(configuration.current_signal_group())
    assert 0 <= group.master <= 9
    assert 0 <= group.slave <= 9
    report["signal_group"] = {
        "master": group.master,
        "slave": group.slave,
        "master_bands": group.master_bands,
        "slave_bands": group.slave_bands,
    }


def test_raw_data_logs_acknowledged_and_restored(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    before = ordered_log_list(device)
    results = []
    for log in RawDataLog:
        if any(entry.name == log.value for entry in before.entries):
            results.append(f"{log.value}:already-subscribed")
            continue
        response = device.execute(log.output(1))
        assert isinstance(response, CommandResponse) and response.accepted
        try:
            registered = any(
                entry.name == log.value for entry in device.execute(log_list()).entries
            )
        finally:
            device.execute(log.stop())
        assert ordered_log_list(device) == before
        results.append(
            {
                "log": log.value,
                "acknowledged": True,
                "subscription_registered": registered,
            }
        )
    report["raw_data_logs"] = results


def test_message_catalogue_is_complete_on_this_build(
    baseband_receiver: tuple[Receiver, dict[str, object]],
) -> None:
    device, report = baseband_receiver
    del device
    families: dict[str, int] = {}
    for entry in BASEBAND_MESSAGE_CATALOGUE.values():
        families[entry.family.value] = families.get(entry.family.value, 0) + 1
    assert len(BASEBAND_MESSAGE_CATALOGUE) == 185
    assert families["ignored"] == 100
    assert sum(families.values()) == 185
    assert spec(147).message_id == 147
    report["message_catalogue"] = {
        "ids": len(BASEBAND_MESSAGE_CATALOGUE),
        "families": families,
        "with_fields": sum(
            1 for e in BASEBAND_MESSAGE_CATALOGUE.values() if e.carries_fields
        ),
        "repeating": sum(1 for e in BASEBAND_MESSAGE_CATALOGUE.values() if e.repeating),
    }
