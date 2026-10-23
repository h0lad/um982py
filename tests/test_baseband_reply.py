"""Checks the boundary behaviour of diagnostic notice parsing."""

import pytest

from um982py.errors import ProtocolError
from um982py.experimental import (
    BasebandCommand,
    BasebandNoticeStream,
    decode_baseband_notice,
    parse_baseband_notice,
    scan_notices,
)


@pytest.mark.parametrize(
    ("raw", "name", "fields"),
    [
        (b"$Parse TimingMode: 1\r\n", "TIMINGMODE", ("1",)),
        (b"$TrackMode,0\r\n", "TRACKMODE", ("0",)),
        (b"$AcqFreqEn,FFFFFFFF\r\n", "ACQFREQ", ("FFFFFFFF",)),
        (b"$SignalGroupConfig,1,2\r\n", "SIGNALGROUP", ("1", "2")),
        (
            b"$Parse EventCofig: 1, 2, 3, 4\r\n",
            "EVENTCONFIG",
            ("1", "2", "3", "4"),
        ),
        (b"$AIENA: 1\r\n", "AIENA", ("1",)),
        (b"LogPPPCMD: 1\r\n", "PPPEN", ("1",)),
        (b"LogPPPRTKCMD: 1\r\n", "PPPRTKEN", ("1",)),
        (b"LogRECINFOENCMD: 1\r\n", "RECINFOEN", ("1",)),
        (
            b"$ParseSendRTCInfoEnFlag: SendRTCInfoEn, 1\r\n",
            "RTCSTATUSEN",
            ("1",),
        ),
        (
            b"$ParseSendJAMInfoEnFlag: SendJAMInfoEn, 1\r\n",
            "JAMSTATUSEN",
            ("1",),
        ),
        (b"$Parse ADRReliablityLevel: 3\r\n", "ADRRELIABLITY", ("3",)),
        (b"$Parse ADRInitial: 2\r\n", "ADRINITIAL", ("2",)),
        (b"$Parse MMP Ena: 1\r\n", "MMPEN", ("1",)),
        (b"$RFSPIRead:0x0000001234\r\n", "RFSPIREAD", ("0000001234",)),
        (b"$RFSPIRead:dead can not parsed!\r\n", "RFSPIREAD_ERROR", ("dead",)),
        (
            b"$RFSPIWrite:dead Address may not correct!\r\n",
            "RFSPIWRITE",
            ("dead",),
        ),
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
    ],
)
def test_notice_framing(raw: bytes, name: str, fields: tuple[str, ...]) -> None:
    notice = parse_baseband_notice(raw)
    assert notice is not None
    assert notice.name == name
    assert notice.fields == fields
    assert notice.raw == raw


def test_bb_log_enable_27_value_line() -> None:
    raw = b",".join(str(index).encode() for index in range(1, 28)) + b"\r\n"
    notice = parse_baseband_notice(raw)
    assert notice is not None
    assert notice.name == "BBLOGEN"
    assert notice.fields == tuple(str(index) for index in range(1, 28))
    record = notice.decode()
    for index in range(1, 28):
        assert record.integer(f"value_{index}") == index


@pytest.mark.parametrize(
    ("raw", "key", "expected"),
    [
        (b"$Parse TimingMode: 1\r\n", "value", 1),
        (b"$Parse TimingMode: -2\r\n", "value", -2),
        (b"$AcqFreqEn,FFFFFFFF\r\n", "mask", 0xFFFFFFFF),
        (b"$RFSPIRead:0x0000001234\r\n", "address", 0x1234),
        (b"$ConfigRF write!\r\n", "operation", "write"),
        (b"$FIFO OverFlow,5,0xdead !!!!!!\r\n", "count", 5),
        (b"$FIFO OverFlow,5,0xdead !!!!!!\r\n", "address", 0xDEAD),
        (b"$CMDReset,dead,1\r\n", "mode", 1),
        (b"#DoSBASCONTROL,1,2,3,4\r\n", "value_4", 4),
    ],
)
def test_notice_decoding(raw: bytes, key: str, expected: object) -> None:
    notice = parse_baseband_notice(raw)
    assert notice is not None
    record = decode_baseband_notice(notice)
    assert record[key] == expected


def test_unknown_notice_raises_on_decode() -> None:
    notice = parse_baseband_notice(b"$Parse TimingMode: 1\r\n")
    assert notice is not None
    # Build a notice directly to test an unknown name.
    from um982py.experimental.baseband_reply import BasebandNotice

    with pytest.raises(ProtocolError, match="Unknown baseband notice"):
        decode_baseband_notice(BasebandNotice("NOT_A_NOTICE", (), b""))


@pytest.mark.parametrize(
    "raw",
    [
        b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,\r\n",
        b"$command,BBCMD $TIMINGMODE,1,response: OK*3B\r\n",
        b"#BESTPOSA,COM1,0,60.0,FINESTEERING,2400,123000,2400,0,18,1;"
        b"SOL_COMPUTED,SINGLE,50.0,30.0,60.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"
        b"*12345678\r\n",
        b"random text\r\n",
        b"\r\n",
        b"",
    ],
)
def test_unrelated_lines_are_not_notices(raw: bytes) -> None:
    assert parse_baseband_notice(raw) is None


def test_command_notice_mapping_is_consistent() -> None:
    assert BasebandCommand.TIMINGMODE.notice == "TIMINGMODE"
    assert BasebandCommand.SIGNALMASK.notice is None
    assert BasebandCommand.SIGNALGROUP.notice == "SIGNALGROUP"
    assert BasebandCommand.RESET.notice == "RESET"
    assert BasebandCommand.BBLOGEN.notice == "BBLOGEN"
    assert BasebandCommand.BBMSG2AP.notice is None
    assert BasebandCommand.LOG.notice == "LOG_SWITCH"
    # Each mapped notice must have a parser pattern.
    for command in BasebandCommand:
        if command.notice is not None:
            assert command.notice in {
                pattern_name for pattern_name, _, _ in _patterns_for_test()
            }


def _patterns_for_test() -> tuple[tuple[str, object, object], ...]:
    from um982py.experimental.baseband_reply import _PATTERNS

    return _PATTERNS


def test_scan_notices_recovers_between_garbage() -> None:
    blob = (
        b"noise"
        + b"$Parse TimingMode: 1\r\n"
        + b"$GPGGA,123519\r\n"
        + b"$TrackMode,0\r\n"
        + b"trailing"
    )
    notices = scan_notices(blob)
    assert [notice.name for notice in notices] == ["TIMINGMODE", "TRACKMODE"]
    assert notices[0].decode().integer("value") == 1
    assert notices[1].decode().integer("value") == 0


def test_notice_stream_handles_fragmentation() -> None:
    stream = BasebandNoticeStream()
    raw = b"$AcqFreqEn,FFFFFFFF\r\n"
    found = []
    for byte in raw:
        found.extend(stream.feed(bytes([byte])))
    assert [notice.name for notice in found] == ["ACQFREQ"]
    assert found[0].decode().integer("mask") == 0xFFFFFFFF
    assert stream.pending == b""


def test_notice_stream_discards_and_finishes() -> None:
    stream = BasebandNoticeStream()
    assert stream.feed(b"not a notice\n") == ()
    assert stream.discarded > 0
    assert stream.finish() == b""
    assert stream.pending == b""
    assert stream.feed(b"$FPGA Version: 2\n")[0].decode().integer("version") == 2


def test_notice_round_trips_through_decode() -> None:
    raw = b"$Parse EventCofig: 1, 2, 3, 4\r\n"
    notice = parse_baseband_notice(raw)
    assert notice is not None
    record = notice.decode()
    assert record.name == "EVENTCONFIG"
    assert [record.integer(f"value_{index}") for index in range(1, 5)] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("raw", "name", "field", "expected"),
    [
        (
            b"$PT,1,5,0,101,102,103,104,105,106,600,00001400,4,42.35,-1250,\r\n",
            "POINT_TRACKING",
            "cn0",
            42.35,
        ),
        (
            b"$PT,2,18,0,120,00001400,4,38.50,-800,1a,200,300,1,2,3,4\r\n",
            "POINT_TRACKING_COMPACT",
            "correlator_1",
            120,
        ),
        (
            b"$PT,3,7,0,88,12,00001400,-500,\r\n",
            "POINT_TRACKING_SHORT",
            "doppler",
            -500,
        ),
        (
            b"$PD,10,8B000000,12345678,\r\n",
            "POINT_DATA",
            "length",
            10,
        ),
        (
            b"$PD L6D,193,8,0x1234,0x5678,\r\n",
            "POINT_DATA_L6",
            "subband",
            "D",
        ),
        (
            b"$SensorADC:0x1, 240, 255\r\n",
            "SENSOR_ADC",
            "channel",
            1,
        ),
        (
            b"$SensorADCCheckSumE:1a,2b\r\n",
            "SENSOR_ADC_CHECKSUM_ERROR",
            "expected",
            0x1A,
        ),
        (
            b"$MonitorCorAcqChan,CoupleChan,1,2,3,4\r\n",
            "MONITOR_COR_ACQ_CHAN",
            "value_4",
            4,
        ),
        (
            b"$ERROR: PosReset Tag:10,2,0x0000001f\r\n",
            "POS_RESET_ERROR",
            "flags",
            0x1F,
        ),
        (
            b"$MsAjust_Inteval,1 2 3 4 5 6 7\r\n",
            "MS_ADJUST_INTERVAL",
            "value_7",
            7,
        ),
        (
            b"$MsAjust_0,11 22\r\n",
            "MS_ADJUST_0",
            "value_2",
            22,
        ),
        (
            b"$MsAjust_3,1 2 3 4\r\n",
            "MS_ADJUST_3",
            "value_4",
            4,
        ),
        (
            b"$BD2IONChErr,7 8 9\r\n",
            "BD2_ION_CHANNEL_ERROR",
            "value_3",
            9,
        ),
        (
            b"$GPS TimeQ Coarse,Last:1, MsCount:2,Tag:3, 4 5, 6 7, 8 9\r\n",
            "TIMEQ_COARSE",
            "system",
            "GPS",
        ),
        (
            b"$Not have Idle Measurement Buffer, Tag,42!\r\n",
            "IDLE_MEASUREMENT_BUFFER",
            "tag",
            42,
        ),
        (
            b"$POSDEBUG,1,0,0,656,2441,557823.000,34,34*End\r\n",
            "POS_DEBUG",
            "detail",
            "1,0,0,656,2441,557823.000,34,34",
        ),
        (
            b"$MPTDEBUG,1;pte,1000*End\r\n",
            "MPT_DEBUG",
            "detail",
            "1;pte,1000",
        ),
        (
            b"$PPPDEBUGMSG,$PPPDATA,Msec:557827000*End\r\n",
            "PPP_DEBUG",
            "source",
            "PPPDEBUGMSG",
        ),
    ],
)
def test_extended_baseband_and_internal_debug_notices(
    raw: bytes, name: str, field: str, expected: object
) -> None:
    notice = parse_baseband_notice(raw)
    assert notice is not None
    assert notice.name == name
    record = notice.decode()
    assert record[field] == expected
