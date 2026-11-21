import json
from dataclasses import replace
from pathlib import Path
from struct import pack

import pytest
from examples.ppp_filter_inspector import analyse_ppp_filter, match_ppp_range
from examples.ppp_filter_inspector.__main__ import main

from conftest import ascii_message
from test_protocol import binary
from um982py.experimental import (
    PppDebugAmbiguity,
    PppDebugUpdateFailure,
    parse_pos_debug,
    parse_ppp_debug,
    parse_ppp_solver_trace,
)
from um982py.messages.frames import BinaryHeader
from um982py.protocol import StreamDecoder
from um982py.protocol.binary import parse_binary
from um982py.receiver_models import (
    PerformanceStatus,
    ReceiverSystemStatus,
    parse_configuration,
)


def test_parse_performance_and_system_status() -> None:
    perf_wire = ascii_message(
        "PERFSTATA",
        "GSPMain,210.00,4.00%,IDLE,4600.00,87.50%,GspMatchedRTKDe,350.00,8.50%NVMLOOPCOUNT:299",
    )
    rx_wire = ascii_message(
        "RXSTATUSA",
        "UM982,HRPT00-S10C-P,cpu750ahb187.50gnss250.00sdram187.50,"
        "GSP_TEST,RTK_TEST,BB_TEST,LOADER_TEST,"
        "2330320000090,ff3391cf0964912b,4b45a0,2026/05/21,0,0,PWM,MINT,MD_100",
    )
    messages = StreamDecoder(strict=True).feed(perf_wire + rx_wire)
    perf = PerformanceStatus.from_message(messages[0])
    assert perf.idle_percent == pytest.approx(87.5)
    assert perf.cpu_load_percent == pytest.approx(12.5)
    assert perf.nvm_loop_count == 299
    assert perf.tasks[0].name == "IDLE"

    sys_status = ReceiverSystemStatus.from_message(messages[1])
    assert sys_status.model == "UM982"
    assert sys_status.cpu_mhz == pytest.approx(750.0)
    assert sys_status.gnss_mhz == pytest.approx(250.0)
    assert sys_status.gsp_version == "GSP_TEST"
    assert sys_status.baseband_version == "BB_TEST"


def test_parse_configuration_extracts_typed_settings() -> None:
    from um982py.protocol.checksums import nmea_checksum

    def cfg_line(body: bytes) -> bytes:
        full = b"$CONFIG," + body
        return full + f"*{nmea_checksum(full):02X}\r\n".encode()

    raw = b"".join(
        (
            cfg_line(b"ANTENNA,CONFIG ANTENNA POWERON"),
            cfg_line(b"SIGNALGROUP,CONFIG SIGNALGROUP 3 6"),
            cfg_line(b"PPP,CONFIG PPP ENABLE AUTO"),
            cfg_line(b"PPP,CONFIG PPP TIMEOUT 120"),
            cfg_line(b"COM1,CONFIG COM1 921600"),
        )
    )
    messages = StreamDecoder().feed(raw)
    cfg = parse_configuration(messages)
    assert cfg.antenna_power == "POWERON"
    assert (
        cfg.signal_group is not None
        and cfg.signal_group.master == 3
        and cfg.signal_group.slave == 6
    )
    assert cfg.ppp_enabled is True
    assert cfg.ppp_service == "AUTO"
    assert cfg.ppp_timeout == 120
    assert cfg.ports["COM1"] == 921600
    assert len(cfg.get("PPP")) == 2


def test_ppp_filter_inspector_analysis_and_replay(tmp_path: Path) -> None:
    ppp_line = (
        b"$PPPDEBUGMSG,$PPPDATA,Msec:559003000SsrT:559001,0,559001,0,0"
        b"Type:8,9,8,6,6CorNum:G24C0E26R0C6;IODE:S8S23"
        b"Vel:-0.015,-0.019,0.050 PrcNum8;dX0.300,0.400,0.000"
        b"S15F1:0.030S18F1:-0.040S20F3:0.120*End\r\n"
    )
    pos_line = (
        b"$POSDEBUG,1,0,0,656,2441,559003.000,33,33,ls=10,0;559002.000,33;"
        b"adr15,20,0.00;flpp,68,0;hgt,559002.00,1,0.0,0.0;0.0,310.5;*End\r\n"
    )
    perf_wire = ascii_message(
        "PERFSTATA",
        "GSPMain,210.00,4.00%,IDLE,4600.00,88.00%NVMLOOPCOUNT:299",
    )
    ppp = parse_ppp_debug(ppp_line)
    pos = parse_pos_debug(pos_line)
    assert ppp is not None and pos is not None
    summary = analyse_ppp_filter([ppp], [pos])
    assert summary.epochs == 1
    assert summary.max_corrected_gps == 24
    assert summary.max_corrected_galileo == 26
    assert summary.max_processed_satellites == 8
    assert summary.step_rms_m == pytest.approx(0.5)
    assert summary.mean_adr_lock_ratio == pytest.approx(0.75)
    assert len(summary.frequency_residuals) == 2

    replay_path = tmp_path / "capture.bin"
    output_path = tmp_path / "out.json"
    replay_path.write_bytes(
        perf_wire
        + binary(b"\x01\x02\x03", message_id=12)
        + ppp_line
        + binary(b"\x01\x02\x03", message_id=12)
        + pos_line
        + ppp_line.replace(b"$PPPDEBUGMSG,", b"$PPPHDEBUGMSG,", 1)
    )
    assert main(["--replay", str(replay_path), "--json", str(output_path)]) == 0
    payload = json.loads(output_path.read_text())
    assert payload["status"] == "ppp_observed"
    assert payload["telemetry_sources"]["ppp_debug_epochs"] == 1
    assert payload["telemetry_sources"]["other_antenna_ppp_debug_epochs"] == 1
    assert payload["analysis"]["cpu_load_percent"] == pytest.approx(12.0)
    assert payload["analysis"]["max_corrected_galileo"] == 26
    assert (
        main(
            [
                "--replay",
                str(replay_path),
                "--json",
                str(output_path),
                "--swap-antennas",
            ]
        )
        == 0
    )
    secondary = json.loads(output_path.read_text())
    assert secondary["antenna"] == 2
    assert [row["source"] for row in secondary["ppp_epochs"]] == ["PPPHDEBUGMSG"]
    replay_path.write_bytes(perf_wire)
    assert main(["--replay", str(replay_path), "--json", str(output_path)]) == 0
    auxiliary = json.loads(output_path.read_text())
    assert auxiliary["status"] == "auxiliary_telemetry_only"
    assert auxiliary["analysis"]["max_corrected_galileo"] is None


def test_ppp_filter_summary_preserves_absent_coverage() -> None:
    summary = analyse_ppp_filter([])
    assert summary.epochs == 0
    assert summary.max_corrected_gps is None
    assert summary.max_corrected_galileo is None
    assert summary.max_corrected_beidou_b2b is None
    assert summary.max_corrected_beidou is None
    assert summary.max_processed_satellites is None


def test_ppp_native_diagnostics_and_range_join(tmp_path: Path) -> None:
    raw = (
        b"$PPPDEBUGMSG,$PPPDATA,Msec:123000SsrT:0,0,0,0,0"
        b"Type:0,0,0,0,0CorNum:G0C0E0R0C0;IODE:S49S89"
        b"Amb2F1:3Sy4F4False;S89F1:0.12S15F3:-0.4*End\r\n"
    )
    record = parse_ppp_debug(raw)
    assert record is not None
    assert record.update_failures == (PppDebugUpdateFailure(4, 4),)
    assert record.ambiguity_diagnostics == (PppDebugAmbiguity(2, 1, 3),)
    assert record.iode_satellites[0].prn is None
    assert record.iode_satellites[1] == record.residuals[0].satellite
    gps_status = 0
    gal_status = 3 << 16 | 12 << 21
    payload = pack("<I", 2) + b"".join(
        pack("<HHdfdffffI", 15, 0, 24000000, 1, 455, 0.1, -2, 42, 55, status)
        for status in (gps_status, gal_status)
    )
    wire = binary(payload, message_id=43)
    message = parse_binary(wire)
    assert isinstance(message.header, BinaryHeader)
    assert len(match_ppp_range((record,), (message,))) == 2
    next_week = replace(message, header=replace(message.header, week=2401))
    assert match_ppp_range((record,), (message, next_week)) == ()
    assert match_ppp_range((record,), (message,), antenna=2) == ()

    ppp_path, range_path, trace_path, report_path = (
        tmp_path / name for name in ("ppp.bin", "range.bin", "trace.txt", "report.json")
    )
    ppp_path.write_bytes(raw)
    range_path.write_bytes(wire)
    trace_path.write_bytes(
        b"PPPGAPVCV-from-GAP 1 2 3 4 5 6 7 8 9\n"
        b": RESET TYPE: 2 CAUSE: gap\n"
        b":Sol 1 2 3 4 5 6 7 clk: 8 9 10 11 12 13 PDOP 1 HDOP 2 VDOP 3 "
        b"dwtrop:4 5 6\n"
    )
    assert (
        main(
            [
                "--replay",
                str(ppp_path),
                "--range-replay",
                str(range_path),
                "--solver-trace",
                str(trace_path),
                "--json",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text())
    assert report["analysis"]["ambiguity_tokens"] == 1
    assert report["analysis"]["update_failures"][0]["present_in_every_epoch"]
    assert report["ppp_epochs"][0]["residuals"][0]["satellite"]["prn"] == 15
    assert report["range_context"][1]["signals"][0]["signal_code"] == 12
    assert report["solver_trace"][0]["fields"]["values"][-1] == 9
    assert report["solver_trace"][1]["fields"]["cause"] == "gap"
    assert report["solver_trace"][2]["fields"]["troposphere"] == [4, 5, 6]
    assert parse_ppp_solver_trace("PPPGAP POS-VCV nan 2 3") is None
