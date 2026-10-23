"""Tests the baseband notice state console against ground truth."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields

import pytest
from examples.baseband_notice_console import (
    LOG_ENABLE_COUNT,
    BasebandState,
    apply_notices,
    solution_summary,
    state_sequence,
)

from um982py.experimental import parse_baseband_notice, scan_notices

NOTICE_LINES: tuple[tuple[bytes, str, tuple[str, ...]], ...] = (
    (b"$Parse TimingMode: 1\r\n", "TIMINGMODE", ("1",)),
    (b"$TrackMode,0\r\n", "TRACKMODE", ("0",)),
    (b"$AcqFreqEn,FFFFFFFF\r\n", "ACQFREQ", ("FFFFFFFF",)),
    (b"$SignalGroupConfig,1,2\r\n", "SIGNALGROUP", ("1", "2")),
    (b"$Parse EventCofig: 1, 2, 3, 4\r\n", "EVENTCONFIG", ("1", "2", "3", "4")),
    (b"$AIENA: 1\r\n", "AIENA", ("1",)),
    (b"LogPPPCMD: 1\r\n", "PPPEN", ("1",)),
    (b"LogPPPRTKCMD: 1\r\n", "PPPRTKEN", ("1",)),
    (b"LogRECINFOENCMD: 1\r\n", "RECINFOEN", ("1",)),
    (b"$ParseSendRTCInfoEnFlag: SendRTCInfoEn, 1\r\n", "RTCSTATUSEN", ("1",)),
    (b"$ParseSendJAMInfoEnFlag: SendJAMInfoEn, 1\r\n", "JAMSTATUSEN", ("1",)),
    (b"$Parse ADRReliablityLevel: 3\r\n", "ADRRELIABLITY", ("3",)),
    (b"$Parse ADRInitial: 2\r\n", "ADRINITIAL", ("2",)),
    (b"$Parse MMP Ena: 1\r\n", "MMPEN", ("1",)),
    (b"$RFSPIRead:0x0000001234\r\n", "RFSPIREAD", ("0000001234",)),
    (b"$RFSPIRead:dead can not parsed!\r\n", "RFSPIREAD_ERROR", ("dead",)),
    (b"$RFSPIWrite:dead Address may not correct!\r\n", "RFSPIWRITE", ("dead",)),
    (b"$ConfigRF write!  \r\n", "RFCONFIG", ("write",)),
    (b"$ConfigRF read!  \r\n", "RFCONFIG", ("read",)),
    (b"$ForceErrorTrap,dead\r\n", "FORCEERRORTRAP", ("dead",)),
    (b"$BBLOGEN:dead can not parsed!\r\n", "BBLOGEN_ERROR", ("dead",)),
    (b"$BB Version: TEST\r\n", "BB_VERSION", ("TEST",)),
    (b"$FPGA Version: 3\r\n", "FPGA_VERSION", ("3",)),
    (b"$FIFO OverFlow,5,0xdead !!!!!!\r\n", "FIFO_OVERFLOW", ("5", "dead")),
    (b"$ErrTrap:CmdDulDef:TIMINGMODE\r\n", "DUPLICATE_COMMAND", ("TIMINGMODE",)),
    (b"$UartBinayCMDOK:\r\n", "UART_CMD_OK", ()),
    (b"$UartBinayCMDFAIL:\r\n", "UART_CMD_FAIL", ()),
    (b"$SPICMDOK:\r\n", "SPI_CMD_OK", ()),
    (b"$SPICMDFAIL:\r\n", "SPI_CMD_FAIL", ()),
    (b"$APCMD:\r\n", "AP_CMD", ()),
    (b"$CMDReset,dead,1\r\n", "RESET", ("dead", "1")),
    (b"$CMDFReset,1\r\n", "FRESET", ("1",)),
    (b"$FlashClearToAp:\r\n", "FLASH_CLEAR", ()),
    (b"#DoSBASCONTROL,1,2,3,4\r\n", "SBASCONTROL", ("1", "2", "3", "4")),
    (b"$DOPPS AP 1 2\r\n", "DOPPS", ("1", "2")),
    (b"$PPSConfigUpdate: Entered, 1, 2\r\n", "PPSCONFIG", ("Entered, 1, 2",)),
    (b"$PPS,S2,1,2,3\r\n", "PPS", ("2", "1,2,3")),
)

SETTING_FIELDS: dict[str, str] = {
    "TIMINGMODE": "timing_mode",
    "TRACKMODE": "track_mode",
    "ACQFREQ": "acquisition_mask",
    "SIGNALGROUP": "signal_group",
    "EVENTCONFIG": "event_config",
    "AIENA": "ai_enable",
    "PPPEN": "ppp_enable",
    "PPPRTKEN": "ppp_rtk_enable",
    "RECINFOEN": "record_info_enable",
    "RTCSTATUSEN": "rtc_status_enable",
    "JAMSTATUSEN": "jam_status_enable",
    "ADRRELIABLITY": "adr_reliability",
    "ADRINITIAL": "adr_initial",
    "MMPEN": "mmp_enable",
    "BBLOGEN": "log_enable",
}

LOG_ENABLE_LINE = (
    b",".join(str(index).encode() for index in range(1, LOG_ENABLE_COUNT + 1)) + b"\r\n"
)

KNOWN_STATE = BasebandState(
    timing_mode=1,
    track_mode=0,
    acquisition_mask=0xFFFFFFFF,
    signal_group=(1, 2),
    event_config=(1, 2, 3, 4),
    ai_enable=1,
    ppp_enable=1,
    ppp_rtk_enable=1,
    record_info_enable=1,
    rtc_status_enable=1,
    jam_status_enable=1,
    adr_reliability=3,
    adr_initial=2,
    mmp_enable=1,
    log_enable=tuple(range(1, LOG_ENABLE_COUNT + 1)),
)

CONFIG_LINES = (
    b"$Parse TimingMode: 1\r\n"
    b"$TrackMode,0\r\n"
    b"$AcqFreqEn,FFFFFFFF\r\n"
    b"$SignalGroupConfig,1,2\r\n"
    b"$Parse EventCofig: 1, 2, 3, 4\r\n"
    b"$AIENA: 1\r\n"
    b"LogPPPCMD: 1\r\n"
    b"LogPPPRTKCMD: 1\r\n"
    b"LogRECINFOENCMD: 1\r\n"
    b"$ParseSendRTCInfoEnFlag: SendRTCInfoEn, 1\r\n"
    b"$ParseSendJAMInfoEnFlag: SendJAMInfoEn, 1\r\n"
    b"$Parse ADRReliablityLevel: 3\r\n"
    b"$Parse ADRInitial: 2\r\n"
    b"$Parse MMP Ena: 1\r\n"
) + LOG_ENABLE_LINE

TRANSCRIPT = (
    b"boot noise\r\n"
    b"$BB Version: TEST\r\n"
    + CONFIG_LINES
    + b"$FPGA Version: 3\r\n"
    + b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,\r\n"
)


@pytest.mark.parametrize(("raw", "name", "fields"), NOTICE_LINES)
def test_every_notice_family_round_trips(
    raw: bytes, name: str, fields: tuple[str, ...]
) -> None:
    notice = parse_baseband_notice(raw)
    assert notice is not None
    assert (notice.name, notice.fields, notice.raw) == (name, fields, raw)
    assert notice.decode().name == name


@pytest.mark.parametrize(("raw", "name", "fields"), NOTICE_LINES)
def test_each_notice_family_updates_only_its_own_setting(
    raw: bytes, name: str, fields: tuple[str, ...]
) -> None:
    del fields
    notice = parse_baseband_notice(raw)
    assert notice is not None
    updated = BasebandState().applied(notice)
    changed = [
        field.name
        for field in dataclass_fields(BasebandState)
        if getattr(updated, field.name) is not None
    ]
    expected = [SETTING_FIELDS[name]] if name in SETTING_FIELDS else []
    assert changed == expected


@pytest.mark.parametrize(("raw", "name", "fields"), NOTICE_LINES)
def test_replaying_a_notice_twice_is_idempotent(
    raw: bytes, name: str, fields: tuple[str, ...]
) -> None:
    del name, fields
    notice = parse_baseband_notice(raw)
    assert notice is not None
    once = BasebandState().applied(notice)
    assert once.applied(notice) == once


def test_synthetic_sequence_reconstructs_the_known_state() -> None:
    assert apply_notices(scan_notices(TRANSCRIPT)) == KNOWN_STATE


def test_partial_line_reconstruction_drops_no_configuration() -> None:
    assert apply_notices(scan_notices(CONFIG_LINES)) == KNOWN_STATE


def test_stream_and_parsed_lines_agree() -> None:
    from_stream = apply_notices(scan_notices(TRANSCRIPT))
    from_lines = apply_notices(
        notice
        for notice in map(parse_baseband_notice, TRANSCRIPT.splitlines(keepends=True))
        if notice is not None
    )
    assert from_stream == from_lines


def test_decoded_values_match_the_wire_text() -> None:
    assert KNOWN_STATE.timing_mode == pytest.approx(1, abs=0)
    assert KNOWN_STATE.acquisition_mask == pytest.approx(0xFFFFFFFF, abs=0)
    assert KNOWN_STATE.signal_group == (1, 2)
    assert KNOWN_STATE.event_config == (1, 2, 3, 4)
    assert len(KNOWN_STATE.log_enable or ()) == pytest.approx(LOG_ENABLE_COUNT, abs=0)


def test_events_leave_a_reconstructed_state_unchanged() -> None:
    recovered = apply_notices(scan_notices(CONFIG_LINES))
    for raw, name, _ in NOTICE_LINES:
        if name in SETTING_FIELDS:
            continue
        notice = parse_baseband_notice(raw)
        assert notice is not None
        assert recovered.applied(notice) == recovered


def test_later_notice_overrides_an_earlier_one() -> None:
    notices = scan_notices(b"$Parse TimingMode: 1\r\n$Parse TimingMode: -2\r\n")
    assert apply_notices(notices).timing_mode == pytest.approx(-2, abs=0)


def test_state_sequence_tracks_each_configuration_change() -> None:
    notices = scan_notices(CONFIG_LINES)
    states = state_sequence(notices)
    assert len(states) == len(notices)
    assert states[-1] == KNOWN_STATE
    assert states[0].timing_mode == pytest.approx(1, abs=0)
    assert BasebandState() not in states


def test_thirty_one_value_line_is_not_a_log_enable_notice() -> None:
    short_line = (
        b",".join(str(index).encode() for index in range(1, LOG_ENABLE_COUNT)) + b"\r\n"
    )
    assert parse_baseband_notice(short_line) is None
    assert apply_notices(scan_notices(short_line)) == BasebandState()


def test_unrelated_lines_leave_the_state_empty() -> None:
    data = b"$GNGGA,,,,,,0,,,,,,,,*78\r\nrandom text\r\n\r\n"
    assert apply_notices(scan_notices(data)) == BasebandState()


def test_receiver_rejection_is_reported_and_device_is_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from unittest.mock import MagicMock

    from examples.baseband_notice_console import __main__ as cli

    from um982py.errors import CommandRejected

    receiver = MagicMock()
    monkeypatch.setattr(cli, "open_receiver", lambda args: receiver)
    monkeypatch.setattr(
        cli,
        "capture_baseband_notices",
        MagicMock(side_effect=CommandRejected("BBNOTICE COM1 ONCHANGED", "ERROR")),
    )
    assert cli.main([]) == 2
    assert '"status": "receiver_rejected"' in capsys.readouterr().out
    receiver.close.assert_called_once()


POSITION_LINES = (
    b"$NAVPOS,1842461,9,16,1,52.520645,13.409484,74.000000,"
    b"3783162.875,901938.310,5038321.497,  20\r\n"
    b"$NAVPOS,859421,9,16,1,52.520645,13.409484,74.000000,"
    b"3783162.875,901938.310,5038321.497,  20\r\n"
)


def test_solution_summary_reports_count_residual_and_jump() -> None:
    summary = solution_summary(scan_notices(POSITION_LINES))
    assert summary["count"] == pytest.approx(2.0)
    assert summary["worst_residual_m"] < 0.01
    assert summary["worst_jump_m"] == pytest.approx(0.0)


def test_solution_summary_is_empty_without_position_lines() -> None:
    summary = solution_summary(scan_notices(CONFIG_LINES))
    assert summary == {"count": 0.0, "worst_residual_m": 0.0, "worst_jump_m": 0.0}
