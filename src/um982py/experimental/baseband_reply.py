"""Baseband diagnostic line parsing."""

import re
from dataclasses import dataclass
from enum import StrEnum

from um982py.errors import ProtocolError
from um982py.messages.record import Record, Value

__all__ = [
    "BasebandNotice",
    "BasebandNoticeStream",
    "decode_baseband_notice",
    "parse_baseband_notice",
    "scan_notices",
]


@dataclass(frozen=True, slots=True)
class BasebandNotice:
    """One framed diagnostic line."""

    name: str
    fields: tuple[str, ...]
    raw: bytes

    def decode(self) -> Record:
        return decode_baseband_notice(self)


MAX_PARTIAL_LINE = 2048
"""Longest tail retained while waiting for a line terminator."""


class FieldKind(StrEnum):
    """How a matched field is converted."""

    UNSIGNED = "u"
    SIGNED = "i"
    HEXADECIMAL = "x"
    FLOAT = "f"
    TEXT = "s"

    def convert(self, text: str) -> Value:
        match self:
            case FieldKind.UNSIGNED | FieldKind.SIGNED:
                return int(text)
            case FieldKind.HEXADECIMAL:
                return int(text, 16)
            case FieldKind.FLOAT:
                return float(text)
            case FieldKind.TEXT:
                return text


_PATTERNS: tuple[
    tuple[str, re.Pattern[bytes], tuple[tuple[str, FieldKind], ...]], ...
] = (
    (
        "BBNOTICE",
        re.compile(
            rb"\$BBNOTICE:usStringSize=(\d+) usTotalLen=(\d+) ucReserved=(\d+) "
            rb"uiTagCount=(\d+) ucBoardType *= *(\d+)$"
        ),
        tuple(
            (name, FieldKind.UNSIGNED)
            for name in (
                "string_size",
                "total_length",
                "reserved",
                "tag_count",
                "board_type",
            )
        ),
    ),
    (
        "NAVPOS",
        re.compile(
            rb"\$NAVPOS,(\d+),(\d+),(-?\d+),(-?\d+),(-?\d+\.\d{6}),(-?\d+\.\d{6}),"
            rb"(-?\d+\.\d{6}),\s*(-?\d+\.\d{3}),\s*(-?\d+\.\d{3}),\s*(-?\d+\.\d{3}),"
            rb"\s*(-?\d+)$"
        ),
        (
            ("tag", FieldKind.UNSIGNED),
            ("field_02", FieldKind.UNSIGNED),
            ("field_03", FieldKind.SIGNED),
            ("field_04", FieldKind.SIGNED),
            ("latitude", FieldKind.FLOAT),
            ("longitude", FieldKind.FLOAT),
            ("height", FieldKind.FLOAT),
            ("x", FieldKind.FLOAT),
            ("y", FieldKind.FLOAT),
            ("z", FieldKind.FLOAT),
            ("field_12", FieldKind.SIGNED),
        ),
    ),
    (
        "NAVVEL",
        re.compile(
            rb"\$NAVVEL,(-?\d+\.\d{3}),(-?\d+\.\d{3}),(-?\d+\.\d{3}),(-?\d+\.\d{3}),"
            rb"(-?\d+\.\d{3}),\s*(-?\d+),\s*(-?\d+\.\d{3})$"
        ),
        (
            ("value_1", FieldKind.FLOAT),
            ("value_2", FieldKind.FLOAT),
            ("value_3", FieldKind.FLOAT),
            ("value_4", FieldKind.FLOAT),
            ("value_5", FieldKind.FLOAT),
            ("value_6", FieldKind.SIGNED),
            ("value_7", FieldKind.FLOAT),
        ),
    ),
    (
        "POS_RESULT",
        re.compile(
            rb"\$PosResult: *(-?\d+) (-?\d+) (-?\d+\.\d+) (-?\d+\.\d+);"
            rb" *(-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+);"
            rb" *(-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+);"
            rb" *(-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+)$"
        ),
        (
            ("value_1", FieldKind.SIGNED),
            ("value_2", FieldKind.SIGNED),
            ("value_3", FieldKind.FLOAT),
            ("value_4", FieldKind.FLOAT),
            ("value_5", FieldKind.FLOAT),
            ("value_6", FieldKind.FLOAT),
            ("value_7", FieldKind.FLOAT),
            ("value_8", FieldKind.FLOAT),
            ("value_9", FieldKind.FLOAT),
            ("value_10", FieldKind.FLOAT),
            ("x", FieldKind.FLOAT),
            ("y", FieldKind.FLOAT),
            ("z", FieldKind.FLOAT),
        ),
    ),
    (
        "GPS_WEEK_ROLL",
        re.compile(rb"\$GPSWeekRoll: *(-?\d+),(-?\d+),(-?\d+)$"),
        tuple((f"value_{i}", FieldKind.SIGNED) for i in range(1, 4)),
    ),
    (
        "SIMUTC",
        re.compile(rb"\$SIMUTC, *(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+)$"),
        tuple((f"value_{i}", FieldKind.SIGNED) for i in range(1, 6)),
    ),
    (
        "ANT_STATUS",
        re.compile(rb"\$AntStatus:(\d+),(\d+)$"),
        (("value_1", FieldKind.UNSIGNED), ("value_2", FieldKind.UNSIGNED)),
    ),
    (
        "SAMPLE_CLOCK",
        re.compile(
            rb"\$SmpClkInit: (-?\d+), N: 0x([0-9A-Fa-f]+), "
            rb"Div:(-?\d+),Reg: 0x([0-9A-Fa-f]+), Cnt:(-?\d+), ClkSel:(-?\d+)$"
        ),
        (
            ("value", FieldKind.SIGNED),
            ("n", FieldKind.HEXADECIMAL),
            ("divider", FieldKind.SIGNED),
            ("register", FieldKind.HEXADECIMAL),
            ("count", FieldKind.SIGNED),
            ("clock_select", FieldKind.SIGNED),
        ),
    ),
    (
        "RF_GROUP",
        re.compile(
            rb"\$GROUP, *(\d+), *(\d+),S: *(\d+),Ant:(\d+),Flag: *(\d+),"
            rb"AIMode:([^,\r\n]+),IFreq: *(-?\d+),Fs: *(\d+),(-?\d+),(-?\d+),"
            rb"CH: *(\d+) - *(\d+),InV:([0-9A-Fa-f]{8})([0-9A-Fa-f]{8})$"
        ),
        (
            ("group_1", FieldKind.UNSIGNED),
            ("group_2", FieldKind.UNSIGNED),
            ("s", FieldKind.UNSIGNED),
            ("antenna", FieldKind.UNSIGNED),
            ("flags", FieldKind.UNSIGNED),
            ("ai_mode", FieldKind.TEXT),
            ("intermediate_frequency", FieldKind.SIGNED),
            ("sample_frequency", FieldKind.UNSIGNED),
            ("value_1", FieldKind.SIGNED),
            ("value_2", FieldKind.SIGNED),
            ("channel_first", FieldKind.UNSIGNED),
            ("channel_last", FieldKind.UNSIGNED),
            ("inversion_word_1", FieldKind.HEXADECIMAL),
            ("inversion_word_2", FieldKind.HEXADECIMAL),
        ),
    ),
    (
        "LOG_SWITCH",
        re.compile(rb"LogSwitchCMD: (-?\d+),(-?\d+),(-?\d+)$"),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 4)),
    ),
    (
        "RUNNING_MODE",
        re.compile(rb"\$ConfigRcvRunningMode,(-?\d+), (-?\d+), (-?\d+)$"),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 4)),
    ),
    (
        "RUNNING_MODE_MASK",
        re.compile(rb"\$ConfigRcvRunningMode,(-?\d+), 0x([0-9A-Fa-f]+)$"),
        (("value", FieldKind.SIGNED), ("mask", FieldKind.HEXADECIMAL)),
    ),
    (
        "TIMINGMODE",
        re.compile(rb"\$Parse TimingMode: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    ("TRACKMODE", re.compile(rb"\$TrackMode,(-?\d+)$"), (("value", FieldKind.SIGNED),)),
    (
        "ACQFREQ",
        re.compile(rb"\$AcqFreqEn,([0-9A-Fa-f]+)$"),
        (("mask", FieldKind.HEXADECIMAL),),
    ),
    (
        "SIGNALGROUP",
        re.compile(rb"\$SignalGroupConfig,(-?\d+),(-?\d+)$"),
        (("value_1", FieldKind.SIGNED), ("value_2", FieldKind.SIGNED)),
    ),
    (
        "EVENTCONFIG",
        re.compile(rb"\$Parse EventCofig: (-?\d+), (-?\d+), (-?\d+), (-?\d+)$"),
        (
            ("value_1", FieldKind.SIGNED),
            ("value_2", FieldKind.SIGNED),
            ("value_3", FieldKind.SIGNED),
            ("value_4", FieldKind.SIGNED),
        ),
    ),
    ("AIENA", re.compile(rb"\$AIENA: (-?\d+)$"), (("value", FieldKind.SIGNED),)),
    ("PPPEN", re.compile(rb"LogPPPCMD: (-?\d+)$"), (("value", FieldKind.SIGNED),)),
    (
        "PPPRTKEN",
        re.compile(rb"LogPPPRTKCMD: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "RECINFOEN",
        re.compile(rb"LogRECINFOENCMD: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "RTCSTATUSEN",
        re.compile(rb"\$ParseSendRTCInfoEnFlag: SendRTCInfoEn, (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "JAMSTATUSEN",
        re.compile(rb"\$ParseSendJAMInfoEnFlag: SendJAMInfoEn, (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "ADRRELIABLITY",
        re.compile(rb"\$Parse ADRReliablityLevel: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "ADRINITIAL",
        re.compile(rb"\$Parse ADRInitial: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "MMPEN",
        re.compile(rb"\$Parse MMP Ena: (-?\d+)$"),
        (("value", FieldKind.SIGNED),),
    ),
    (
        "RFSPIREAD",
        re.compile(rb"\$RFSPIRead:0x([0-9A-Fa-f]+)$"),
        (("address", FieldKind.HEXADECIMAL),),
    ),
    (
        "RFSPIREAD_ERROR",
        re.compile(rb"\$RFSPIRead:([0-9A-Fa-f]+) can not parsed!$"),
        (("value", FieldKind.HEXADECIMAL),),
    ),
    (
        "RFSPIWRITE",
        re.compile(rb"\$RFSPIWrite:([0-9A-Fa-f]+) Address may not correct!$"),
        (("address", FieldKind.HEXADECIMAL),),
    ),
    (
        "RFSPIWRITE_PARSE_ERROR",
        re.compile(rb"\$RFSPIRead:([0-9A-Fa-f]+)x can not parsed!$"),
        (("value", FieldKind.HEXADECIMAL),),
    ),
    (
        "RFCONFIG",
        re.compile(rb"\$ConfigRF (write|read)!\s*$"),
        (("operation", FieldKind.TEXT),),
    ),
    (
        "FORCEERRORTRAP",
        re.compile(rb"\$ForceErrorTrap,([0-9A-Fa-f]+)$"),
        (("value", FieldKind.HEXADECIMAL),),
    ),
    (
        "BBLOGEN_ERROR",
        re.compile(rb"\$BBLOGEN:([0-9A-Fa-f]+) can not parsed!$"),
        (("value", FieldKind.HEXADECIMAL),),
    ),
    (
        "BBLOGEN",
        re.compile(
            rb"(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),"
            rb"(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),"
            rb"(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),"
            rb"(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+)$"
        ),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 28)),
    ),
    ("BB_VERSION", re.compile(rb"\$BB Version: (.*)$"), (("version", FieldKind.TEXT),)),
    (
        "FPGA_VERSION",
        re.compile(rb"\$FPGA Version: (-?\d+)$"),
        (("version", FieldKind.SIGNED),),
    ),
    (
        "FIFO_OVERFLOW",
        re.compile(rb"\$FIFO OverFlow,(\d+),0x([0-9A-Fa-f]+) !!!!!!$"),
        (("count", FieldKind.UNSIGNED), ("address", FieldKind.HEXADECIMAL)),
    ),
    (
        "DUPLICATE_COMMAND",
        re.compile(rb"\$ErrTrap:CmdDulDef:(.*)$"),
        (("command", FieldKind.TEXT),),
    ),
    ("UART_CMD_OK", re.compile(rb"\$UartBinayCMDOK:$"), ()),
    ("UART_CMD_FAIL", re.compile(rb"\$UartBinayCMDFAIL:$"), ()),
    ("SPI_CMD_OK", re.compile(rb"\$SPICMDOK:$"), ()),
    ("SPI_CMD_FAIL", re.compile(rb"\$SPICMDFAIL:$"), ()),
    ("AP_CMD", re.compile(rb"\$APCMD:$"), ()),
    (
        "RESET",
        re.compile(rb"\$CMDReset,([0-9A-Fa-f]+),(-?\d+)$"),
        (("value", FieldKind.HEXADECIMAL), ("mode", FieldKind.SIGNED)),
    ),
    ("FRESET", re.compile(rb"\$CMDFReset,(-?\d+)$"), (("value", FieldKind.SIGNED),)),
    ("FLASH_CLEAR", re.compile(rb"\$FlashClearToAp:$"), ()),
    (
        "SBASCONTROL",
        re.compile(rb"#DoSBASCONTROL,(-?\d+),(-?\d+),(-?\d+),(-?\d+)$"),
        (
            ("value_1", FieldKind.SIGNED),
            ("value_2", FieldKind.SIGNED),
            ("value_3", FieldKind.SIGNED),
            ("value_4", FieldKind.SIGNED),
        ),
    ),
    (
        "DOPPS",
        re.compile(rb"\$DOPPS AP (-?\d+) (-?\d+)$"),
        (("value_1", FieldKind.SIGNED), ("value_2", FieldKind.SIGNED)),
    ),
    (
        "PPSCONFIG",
        re.compile(rb"\$PPSConfigUpdate: (.*)$"),
        (("detail", FieldKind.TEXT),),
    ),
    (
        "PPS",
        re.compile(rb"\$PPS,S([1234]),(.*)$"),
        (("part", FieldKind.TEXT), ("detail", FieldKind.TEXT)),
    ),
    (
        "POINT_TRACKING",
        re.compile(
            rb"\$PT,(-?\d+),(-?\d+),(-?\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),"
            rb"(\d+),([0-9A-Fa-f]{8}),(-?\d+),(-?\d+\.\d+),(-?\d+)"
            rb"(?:,([^\r\n]*))?$"
        ),
        (
            ("channel", FieldKind.SIGNED),
            ("prn", FieldKind.SIGNED),
            ("system_signal", FieldKind.SIGNED),
            ("correlator_1", FieldKind.UNSIGNED),
            ("correlator_2", FieldKind.UNSIGNED),
            ("correlator_3", FieldKind.UNSIGNED),
            ("correlator_4", FieldKind.UNSIGNED),
            ("correlator_5", FieldKind.UNSIGNED),
            ("correlator_6", FieldKind.UNSIGNED),
            ("lock_count", FieldKind.UNSIGNED),
            ("tracking_status", FieldKind.HEXADECIMAL),
            ("state", FieldKind.SIGNED),
            ("cn0", FieldKind.FLOAT),
            ("doppler", FieldKind.SIGNED),
            ("detail", FieldKind.TEXT),
        ),
    ),
    (
        "POINT_TRACKING_COMPACT",
        re.compile(
            rb"\$PT,(-?\d+),(-?\d+),(-?\d+),(\d+),([0-9A-Fa-f]{8}),(-?\d+),"
            rb"(-?\d+\.\d+),(-?\d+),([^\r\n]+)$"
        ),
        (
            ("channel", FieldKind.SIGNED),
            ("prn", FieldKind.SIGNED),
            ("system_signal", FieldKind.SIGNED),
            ("correlator_1", FieldKind.UNSIGNED),
            ("tracking_status", FieldKind.HEXADECIMAL),
            ("state", FieldKind.SIGNED),
            ("cn0", FieldKind.FLOAT),
            ("doppler", FieldKind.SIGNED),
            ("detail", FieldKind.TEXT),
        ),
    ),
    (
        "POINT_TRACKING_SHORT",
        re.compile(
            rb"\$PT,(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),([0-9A-Fa-f]{8}),"
            rb"(-?\d+),?$"
        ),
        (
            ("channel", FieldKind.SIGNED),
            ("prn", FieldKind.SIGNED),
            ("system_signal", FieldKind.SIGNED),
            ("correlator_1", FieldKind.SIGNED),
            ("lock_count", FieldKind.SIGNED),
            ("tracking_status", FieldKind.HEXADECIMAL),
            ("doppler", FieldKind.SIGNED),
        ),
    ),
    (
        "POINT_DATA",
        re.compile(rb"\$PD,(\d+),([0-9A-Fa-fxX,]+?)$"),
        (("length", FieldKind.UNSIGNED), ("words", FieldKind.TEXT)),
    ),
    (
        "POINT_DATA_L6",
        re.compile(rb"\$PD L6([DE]),(\d+),(\d+),([0-9A-Fa-fxX,]+?)$"),
        (
            ("subband", FieldKind.TEXT),
            ("prn", FieldKind.UNSIGNED),
            ("length", FieldKind.UNSIGNED),
            ("words", FieldKind.TEXT),
        ),
    ),
    (
        "SENSOR_ADC",
        re.compile(rb"\$SensorADC:0x([0-9A-Fa-f]+), *(-?\d+), *(-?\d+)$"),
        (
            ("channel", FieldKind.HEXADECIMAL),
            ("value_1", FieldKind.SIGNED),
            ("value_2", FieldKind.SIGNED),
        ),
    ),
    (
        "AVG_SENSOR_ADC",
        re.compile(rb"\$AvgSensorADC: *([^\r\n]+)$"),
        (("native_values", FieldKind.TEXT),),
    ),
    (
        "SENSOR_ADC_CHECKSUM_ERROR",
        re.compile(rb"\$SensorADCCheckSumE:([0-9A-Fa-f]+),([0-9A-Fa-f]+)$"),
        (("expected", FieldKind.HEXADECIMAL), ("actual", FieldKind.HEXADECIMAL)),
    ),
    (
        "MONITOR_COR_ACQ_CHAN",
        re.compile(rb"\$MonitorCorAcqChan,CoupleChan,(-?\d+),(-?\d+),(-?\d+),(-?\d+)$"),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 5)),
    ),
    (
        "POS_RESET_ERROR",
        re.compile(rb"\$ERROR: PosReset Tag:(-?\d+),(-?\d+),0x([0-9A-Fa-f]+)$"),
        (
            ("tag", FieldKind.SIGNED),
            ("value", FieldKind.SIGNED),
            ("flags", FieldKind.HEXADECIMAL),
        ),
    ),
    (
        "MS_ADJUST_INTERVAL",
        re.compile(
            rb"\$MsAjust_Inteval,(-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) "
            rb"(-?\d+)$"
        ),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 8)),
    ),
    (
        "MS_ADJUST_0",
        re.compile(rb"\$MsAjust_0,(-?\d+) (-?\d+)$"),
        (("value_1", FieldKind.SIGNED), ("value_2", FieldKind.SIGNED)),
    ),
    (
        "MS_ADJUST_3",
        re.compile(rb"\$MsAjust_3,(-?\d+) (-?\d+) (-?\d+) (-?\d+)$"),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 5)),
    ),
    (
        "BD2_ION_CHANNEL_ERROR",
        re.compile(rb"\$BD2IONChErr,(-?\d+) (-?\d+) (-?\d+)$"),
        tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 4)),
    ),
    (
        "TIMEQ_COARSE",
        re.compile(
            rb"\$(\S+) TimeQ Coarse,Last:(-?\d+), MsCount:(-?\d+),Tag:(-?\d+), "
            rb"*(-?\d+) (-?\d+), *(-?\d+) (-?\d+), *(-?\d+) (-?\d+)$"
        ),
        (
            ("system", FieldKind.TEXT),
            ("last", FieldKind.SIGNED),
            ("ms_count", FieldKind.SIGNED),
            ("tag", FieldKind.SIGNED),
            *(tuple((f"value_{index}", FieldKind.SIGNED) for index in range(1, 7))),
        ),
    ),
    (
        "IDLE_MEASUREMENT_BUFFER",
        re.compile(rb"\$Not have Idle Measurement Buffer, Tag,(-?\d+)!$"),
        (("tag", FieldKind.SIGNED),),
    ),
    (
        "POS_DEBUG",
        re.compile(rb"\$POSDEBUG,([^\r\n]*)\*End$"),
        (("detail", FieldKind.TEXT),),
    ),
    (
        "MPT_DEBUG",
        re.compile(rb"\$MPTDEBUG,([^\r\n]*)\*End$"),
        (("detail", FieldKind.TEXT),),
    ),
    (
        "PVT_DEBUG",
        re.compile(rb"\$PVTDEBUG,([^\r\n]*)\*End$"),
        (("detail", FieldKind.TEXT),),
    ),
    (
        "PPP_DEBUG",
        re.compile(rb"\$(PPPDEBUGMSG|PPPHDEBUGMSG),\$PPPDATA,([^\r\n]*)\*End$"),
        (("source", FieldKind.TEXT), ("detail", FieldKind.TEXT)),
    ),
)


def parse_baseband_notice(raw: bytes) -> BasebandNotice | None:
    """Frame a diagnostic line, or return ``None``."""
    line = raw.rstrip(b"\r\n")
    if not line:
        return None
    for name, pattern, _ in _PATTERNS:
        match = pattern.fullmatch(line)
        if match is not None:
            return BasebandNotice(
                name,
                tuple(
                    "" if group is None else group.decode("latin1")
                    for group in match.groups()
                ),
                bytes(raw),
            )
    return None


def _search_notice(line: bytes) -> BasebandNotice | None:
    """Frame the earliest notice anywhere inside ``line``."""
    best: tuple[int, BasebandNotice] | None = None
    for name, pattern, _ in _PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        start = match.start()
        if best is None or start < best[0]:
            best = (
                start,
                BasebandNotice(
                    name,
                    tuple(
                        "" if group is None else group.decode("latin1")
                        for group in match.groups()
                    ),
                    line[start:],
                ),
            )
    return None if best is None else best[1]


def decode_baseband_notice(notice: BasebandNotice) -> Record:
    """Decode a notice into a ``Record``."""
    for name, _, field_specs in _PATTERNS:
        if name == notice.name:
            entries: list[tuple[str, Value]] = []
            for field_name, kind in field_specs:
                entries.append((field_name, kind.convert(notice.fields[len(entries)])))
            return Record(notice.name, tuple(entries))
    raise ProtocolError(f"Unknown baseband notice: {notice.name}")


class BasebandNoticeStream:
    """Scans diagnostic lines and resynchronises after malformed input."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.discarded = 0

    @property
    def pending(self) -> bytes:
        return bytes(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.discarded = 0

    def _keep_possible_partial_line(self) -> None:
        """Discard everything that cannot still grow into a notice."""
        if len(self._buffer) > MAX_PARTIAL_LINE:
            del self._buffer[:-MAX_PARTIAL_LINE]

    def finish(self) -> bytes:
        remainder = bytes(self._buffer)
        self._buffer.clear()
        return remainder

    def feed(self, data: bytes) -> tuple[BasebandNotice, ...]:
        self._buffer.extend(data)
        notices: list[BasebandNotice] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                self._keep_possible_partial_line()
                return tuple(notices)
            raw = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            notice = parse_baseband_notice(raw)
            if notice is None:
                notice = _search_notice(raw.rstrip(b"\r\n"))
            if notice is not None:
                notices.append(notice)
            else:
                self.discarded += len(raw)
        return tuple(notices)


def scan_notices(data: bytes) -> tuple[BasebandNotice, ...]:
    """Return every recognised notice in ``data`` and ignore trailing bytes."""
    return BasebandNoticeStream().feed(data)
