import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from time import monotonic

import pytest

from um982py import AsyncReceiver, Receiver
from um982py.commands import Log, configuration, logging, queries
from um982py.commands.core import action
from um982py.commands.types import NmeaVersion, Trigger
from um982py.errors import CommandRejected, ResponseTimeout, UM982Error
from um982py.experimental import FirmwareLog, firmware_info
from um982py.experimental.capture import ordered_log_list
from um982py.messages import AsciiHeader, AsciiMessage, Fix, Sentence

pytestmark = pytest.mark.hardware


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return {}


def state(receiver: Receiver) -> dict[str, object]:
    configuration_records = receiver.collect(queries.configuration())
    return {
        "configuration": sorted(m.raw.decode().strip() for m in configuration_records),
        "mode": receiver.execute(queries.mode()).fields,
        "masks": tuple(m.fields for m in receiver.collect(queries.masks())),
        "logs": asdict(ordered_log_list(receiver)),
    }


@pytest.fixture(scope="module")
def receiver(
    request: pytest.FixtureRequest, report: dict[str, object]
) -> Iterator[Receiver]:
    port = request.config.getoption("--hardware-port")
    baud = request.config.getoption("--hardware-baud")
    with Receiver.connect(port, baud, timeout=5) as device:
        before = state(device)
        report["port"] = port
        report["baud"] = baud
        report["version"] = asdict(device.version())
        try:
            yield device
        finally:
            after = state(device)
            report["state_restored"] = before == after
            report["decoder_errors"] = [str(error) for error in device.decoder.errors]
            Path(request.config.getoption("--hardware-report")).write_text(
                json.dumps(report, indent=2) + "\n"
            )
            assert after == before
            assert not device.decoder.errors


def test_identity(receiver: Receiver, report: dict[str, object]) -> None:
    a, b = receiver.version(), receiver.version(binary=True)
    assert a.model == b.model == "UM982"
    assert a.build == b.build
    assert a.serial_number == b.serial_number
    assert a.efuse_id == b.efuse_id
    a_info = receiver.execute(firmware_info())
    b_info = receiver.execute(firmware_info(binary=True))
    assert a_info.model == b_info.model == a.model
    assert a_info.serial_number == b_info.serial_number == a.serial_number
    assert a_info.secondary_version == b_info.secondary_version
    report["identity"] = "passed"


def test_firmware_queries(receiver: Receiver, report: dict[str, object]) -> None:
    results = []
    # Query diagnostics before epoch-driven RANGE logs.
    for log in sorted(FirmwareLog, key=lambda log: log != FirmwareLog.HEADINGOFFSET):
        for binary in (False, True):
            if log == FirmwareLog.RXSTATUS and binary:
                continue
            command = log.read(binary=binary)
            sys.stderr.write(f"  query {log.wire_name(binary=binary)}\n")
            sys.stderr.flush()
            bodies = (
                receiver.collect(command)
                if log == FirmwareLog.SATVIS2
                else (receiver.execute(command),)
            )
            for body in bodies:
                assert body.name == log.value
                if log in (FirmwareLog.RANGE, FirmwareLog.RANGEH):
                    assert len(body.records("observations")) == body.integer("count")
                if log in (FirmwareLog.SATVIS, FirmwareLog.SATVIS2):
                    assert len(body.records("satellites")) == body.integer("count")
            if log == FirmwareLog.SATVIS2:
                report[log.wire_name(binary=binary) + "_frames"] = len(bodies)
            results.append(log.wire_name(binary=binary))
    report["firmware_queries"] = results


def test_firmware_logging(receiver: Receiver, report: dict[str, object]) -> None:
    before = ordered_log_list(receiver)
    results = []
    for log in FirmwareLog:
        if log in (FirmwareLog.HEADINGOFFSET, FirmwareLog.RXSTATUS):
            continue
        for binary in (False, True):
            name = log.wire_name(binary=binary)
            if any(entry.name == name for entry in before.entries):
                continue
            sys.stderr.write(f"  subscribe {name}\n")
            sys.stderr.flush()
            # Drain responses to earlier queries before testing subscriptions.
            while True:
                try:
                    receiver.receive(timeout=0.01)
                except ResponseTimeout:
                    break
            try:
                interval = Trigger.ON_CHANGED if log.onchanged_only else 1
                receiver.execute(log.output(interval, binary=binary))
                deadline = monotonic() + 3
                while True:
                    message = receiver.receive(
                        timeout=max(0.01, deadline - monotonic())
                    )
                    if log.request(binary=binary).matches(message):
                        assert log.decode(message).name == log.value
                        results.append(name)
                        break
                    assert monotonic() < deadline, f"No output for {name}"
            finally:
                receiver.execute(log.stop(binary=binary))
            assert ordered_log_list(receiver) == before
    report["firmware_logging"] = results


def test_firmware_invalid_settings(
    receiver: Receiver, report: dict[str, object]
) -> None:
    # Parsers reject the command before applying its payload.
    commands = (
        "CONFIG MSM 31",
        "CONFIG MSM 33",
        "CONFIG MSM 63",
        "CONFIG MSM 65",
        "CONFIG TRACKMODE 2",
        "CONFIG ANTISPOOF ENABLE 5",
        "CONFIG ANTISPOOF DISABLE 1",
        "CONFIG HEADING2 INVALID",
        "CONFIG RTKIFC INVALID",
        "CONFIG RTCMOUTPUT INVALID",
        "CONFIG BASEBIAS 49",
        "CONFIG BASEBIAS 801",
        "CONFIG BASEOBSFILTER ENABLE 61",
        "CONFIG IONLEVEL 0.49",
        "CONFIG IONLEVEL 3.01",
    )
    results = []
    for text in commands:
        with pytest.raises(CommandRejected) as error:
            receiver.execute(action(text))
        results.append({"command": text, "error": str(error.value)})
    report["firmware_invalid_settings"] = results


def test_navigation_formats(receiver: Receiver, report: dict[str, object]) -> None:
    a = receiver.execute(queries.best_navigation())
    b = receiver.execute(queries.best_navigation(binary=True))
    assert abs(a.latitude - b.latitude) < 0.001
    assert abs(a.longitude - b.longitude) < 0.001
    assert abs(a.altitude_msl - b.altitude_msl) < 30
    report["navigation_formats"] = "passed"


def test_temporary_logging(receiver: Receiver, report: dict[str, object]) -> None:
    before = ordered_log_list(receiver)
    if any(entry.name == "BESTNAVA" for entry in before.entries):
        pytest.skip("BESTNAVA is already configured")
    seen = 0
    try:
        receiver.execute(logging.output("BESTNAVA", 0.2))
        end = monotonic() + 3
        while monotonic() < end:
            message = receiver.receive(timeout=1)
            if isinstance(message, AsciiMessage) and message.name == "BESTNAVA":
                seen += 1
        assert seen >= 1
    finally:
        receiver.execute(logging.stop("BESTNAVA"))
    assert ordered_log_list(receiver) == before
    report["temporary_logging"] = {"passed": True, "records_in_three_seconds": seen}


def test_nmea_configuration(receiver: Receiver, report: dict[str, object]) -> None:
    records = receiver.collect(queries.configuration())
    original = next(
        m.fields[-1].split()[-1] for m in records if m.fields[0] == "NMEAVERSION"
    )
    selected = NmeaVersion.V411 if original == "V410" else NmeaVersion.V410
    try:
        receiver.execute(configuration.nmea_version(selected))
        changed = receiver.collect(queries.configuration())
        assert any(m.fields[-1].endswith(selected.value) for m in changed)
    finally:
        receiver.execute(configuration.nmea_version(NmeaVersion(original)))
    report["nmea_configuration"] = "passed and restored"


def test_command_checksum_mode(receiver: Receiver, report: dict[str, object]) -> None:
    try:
        receiver.execute(configuration.command_checksums(enabled=True))
        receiver.checksummed = True
        assert receiver.version().build > 0
    finally:
        receiver.checksummed = True
        try:
            receiver.execute(configuration.command_checksums(enabled=False))
        except UM982Error:
            receiver.checksummed = False
            receiver.execute(configuration.command_checksums(enabled=False))
        receiver.checksummed = False
    report["command_checksum_mode"] = "passed and restored"


def test_async_hardware(receiver: Receiver, report: dict[str, object]) -> None:
    async def run() -> None:
        adapter = AsyncReceiver(receiver)
        assert (await adapter.version()).build > 0
        assert (await adapter.execute(firmware_info())).model == "UM982"

    asyncio.run(run())
    report["async_queries"] = "passed"


def test_acquisition(
    receiver: Receiver, request: pytest.FixtureRequest, report: dict[str, object]
) -> None:
    end = monotonic() + request.config.getoption("--acquisition-seconds")
    fix = receiver.execute(queries.fix())
    while not fix.valid and monotonic() < end:
        message = receiver.receive(timeout=3)
        if isinstance(message, Sentence) and message.kind == "GGA":
            fix = Fix.from_message(message)
    report["acquisition"] = {
        "valid": fix.valid,
        "quality": fix.quality,
        "satellites": fix.satellites,
    }
    if not fix.valid:
        pytest.skip("No valid GNSS fix within acquisition window")
    assert fix.satellites > 0
    best = receiver.execute(queries.best_navigation())
    assert fix.latitude is not None and abs(fix.latitude - best.latitude) < 0.001
    assert fix.longitude is not None and abs(fix.longitude - best.longitude) < 0.001
    message = receiver.execute(logging.request("BESTNAVA"))
    assert isinstance(message, AsciiMessage) and isinstance(message.header, AsciiHeader)
    assert message.header.time_status == "FINE"


def test_dual_antenna_heading(receiver: Receiver, report: dict[str, object]) -> None:
    heading = receiver.execute(queries.heading())
    report["heading"] = asdict(heading)
    if not heading.valid:
        pytest.skip("Valid dual-antenna heading is unavailable")
    assert heading.degrees is not None and 0 <= heading.degrees <= 360


def test_rtcm_rtk_prerequisite() -> None:
    pytest.skip("No RTCM correction source configured for this test session")


def test_sustained_stream(
    receiver: Receiver, request: pytest.FixtureRequest, report: dict[str, object]
) -> None:
    duration = request.config.getoption("--soak-seconds")
    start = monotonic()
    end = start + duration
    query_interval = min(2.0, duration / 3)
    next_query = start + query_interval
    counts: Counter[str] = Counter()
    queries_completed = 0
    maximum_pending = 0
    while monotonic() < end:
        try:
            message = receiver.receive(timeout=2)
        except ResponseTimeout:
            pytest.fail("Receiver stopped streaming during soak")
        if isinstance(message, Sentence):
            counts[message.name] += 1
        maximum_pending = max(maximum_pending, len(receiver.decoder.pending))
        if monotonic() >= next_query:
            assert receiver.version().build > 0
            queries_completed += 1
            next_query += query_interval
    report["soak"] = {
        "seconds": monotonic() - start,
        "sentences": dict(counts),
        "queries": queries_completed,
        "maximum_partial_frame_bytes": maximum_pending,
    }
    assert counts["GNGGA"] >= duration * 0.8
    assert queries_completed >= 1
    assert not receiver.decoder.errors


def test_documented_log_catalogue(
    receiver: Receiver, report: dict[str, object]
) -> None:
    checked = []
    for log, binary_format in (
        (Log.UNILOGLIST, False),
        (Log.KSXT, False),
        (Log.GPZDA, False),
        (Log.SATSINFO, True),
        (Log.OBSVM, True),
        (Log.HWSTATUS, True),
    ):
        body = receiver.execute(log.read(binary=binary_format))
        assert body.message is not None and body.message.raw
        assert body
        checked.append(log.value)
    report["documented_log_catalogue"] = checked
