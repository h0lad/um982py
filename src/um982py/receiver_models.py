"""Typed models for extended diagnostic records."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from struct import unpack_from
from typing import Self

from um982py.commands.configuration.receiver import SignalGroup
from um982py.commands.core import Command
from um982py.commands.logging import output
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages.frames import (
    AsciiMessage,
    BinaryMessage,
    CommandResponse,
    Message,
    Sentence,
)


@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    count: int
    component: str | int
    authorization: str
    serial_number: str
    model: str
    software: str
    secondary_version: str
    efuse_id: str
    compiled: str

    @classmethod
    def from_message(cls, message: Message) -> Self:
        try:
            if isinstance(message, AsciiMessage) and message.name == "FWINFOA":
                if len(message.fields) != 9:
                    raise ProtocolError("Expected nine FWINFO fields")
                return cls(int(message.fields[0]), *message.fields[1:])
            if (
                isinstance(message, BinaryMessage)
                and message.header.message_id == 11277
            ):
                if len(message.payload) != 368:
                    raise ProtocolError("Expected 368-byte FWINFO payload")
                count, component = unpack_from("<II", message.payload)
                values = tuple(
                    message.payload[start:end].split(b"\0", 1)[0].decode("ascii")
                    for start, end in (
                        (8, 137),
                        (137, 203),
                        (203, 236),
                        (236, 269),
                        (269, 302),
                        (302, 335),
                        (335, 368),
                    )
                )
                return cls(count, component, *values)
        except (ValueError, UnicodeError) as error:
            raise ProtocolError("Invalid FWINFO field") from error
        raise ProtocolError("Not a FWINFO message")


@dataclass(frozen=True, slots=True)
class LogEntry:
    name: str
    port: Port
    interval: float | Trigger

    def command(self) -> Command[CommandResponse]:
        return output(self.name, self.interval, port=self.port)


@dataclass(frozen=True, slots=True)
class LogList:
    entries: tuple[LogEntry, ...]

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if not isinstance(message, AsciiMessage) or message.name not in (
            "LOGLISTA",
            "LOGLIST",
        ):
            raise ProtocolError("Not a LOGLIST message")
        try:
            count = int(message.fields[0])
            records = [field for field in message.fields[1:] if field.strip()]
            if count != len(records):
                raise ProtocolError("LOGLIST count mismatch")
            entries = []
            for record in records:
                name, port, trigger = record.split()
                interval = (
                    Trigger(trigger) if trigger == "ONCHANGED" else float(trigger)
                )
                if isinstance(interval, float) and (
                    not isfinite(interval) or interval <= 0
                ):
                    raise ValueError("Invalid log interval")
                entries.append(LogEntry(name, Port(port), interval))
            return cls(tuple(entries))
        except (IndexError, ValueError) as error:
            raise ProtocolError("Malformed LOGLIST record") from error


@dataclass(frozen=True, slots=True)
class TaskPerformance:
    """Cumulative runtime and CPU share of one RTOS task from PERFSTATA."""

    name: str
    runtime_seconds: float
    cpu_percent: float


@dataclass(frozen=True, slots=True)
class PerformanceStatus:
    """RTOS task CPU utilization and NVM loop counter from PERFSTATA."""

    tasks: tuple[TaskPerformance, ...]
    idle_percent: float
    cpu_load_percent: float
    nvm_loop_count: int | None

    @classmethod
    def from_message(cls, message: Message) -> Self:
        """Decode a PERFSTATA ASCII message into task CPU statistics."""
        if not isinstance(message, AsciiMessage) or message.name != "PERFSTATA":
            raise ProtocolError("Not a PERFSTATA message")
        fields = message.fields
        if len(fields) < 3 or len(fields) % 3 != 0:
            raise ProtocolError("Malformed PERFSTATA field count")
        tasks: list[TaskPerformance] = []
        nvm_loops: int | None = None
        try:
            for index in range(0, len(fields), 3):
                name = fields[index].strip()
                runtime = float(fields[index + 1])
                pct_raw = fields[index + 2].strip()
                if "NVMLOOPCOUNT:" in pct_raw:
                    pct_part, nvm_part = pct_raw.split("NVMLOOPCOUNT:", 1)
                    nvm_loops = int(nvm_part)
                else:
                    pct_part = pct_raw
                percent = float(pct_part.rstrip("%"))
                if not isfinite(runtime) or not isfinite(percent):
                    raise ValueError("Non-finite PERFSTATA value")
                tasks.append(TaskPerformance(name, runtime, percent))
        except ValueError as error:
            raise ProtocolError("Malformed PERFSTATA field") from error
        idle = next((t.cpu_percent for t in tasks if t.name.upper() == "IDLE"), 0.0)
        ordered = tuple(sorted(tasks, key=lambda item: (-item.cpu_percent, item.name)))
        return cls(
            tasks=ordered,
            idle_percent=idle,
            cpu_load_percent=round(max(0.0, 100.0 - idle), 4),
            nvm_loop_count=nvm_loops,
        )


_CLOCK_PATTERN = re.compile(
    r"^cpu(\d+(?:\.\d+)?)ahb(\d+(?:\.\d+)?)gnss(\d+(?:\.\d+)?)sdram(\d+(?:\.\d+)?)$"
)


@dataclass(frozen=True, slots=True)
class ReceiverSystemStatus:
    """Hardware clocks and component builds decoded from RXSTATUSA."""

    model: str
    authorization: str
    cpu_mhz: float
    ahb_mhz: float
    gnss_mhz: float
    sdram_mhz: float
    gsp_version: str
    rtk_version: str
    baseband_version: str
    loader_version: str
    serial_number: str
    efuse_id: str
    compiled: str
    track_summary: str

    @classmethod
    def from_message(cls, message: Message) -> Self:
        """Decode an RXSTATUSA message into typed clock and version metadata."""
        if not isinstance(message, AsciiMessage) or message.name != "RXSTATUSA":
            raise ProtocolError("Not an RXSTATUSA message")
        if len(message.fields) < 16:
            raise ProtocolError("Expected 16 RXSTATUSA fields")
        fields = message.fields
        match = _CLOCK_PATTERN.match(fields[2])
        if match is None:
            raise ProtocolError("Malformed RXSTATUSA clock field")
        return cls(
            model=fields[0],
            authorization=fields[1],
            cpu_mhz=float(match.group(1)),
            ahb_mhz=float(match.group(2)),
            gnss_mhz=float(match.group(3)),
            sdram_mhz=float(match.group(4)),
            gsp_version=fields[3],
            rtk_version=fields[4],
            baseband_version=fields[5],
            loader_version=fields[6],
            serial_number=fields[7],
            efuse_id=fields[8],
            compiled=fields[10],
            track_summary=fields[14],
        )


@dataclass(frozen=True, slots=True)
class ReceiverConfig:
    """Structured receiver configuration parsed from CONFIG sentences."""

    antenna_power: str | None
    nmea_version: str | None
    signal_group: SignalGroup | None
    ppp_enabled: bool | None
    ppp_service: str | None
    ppp_timeout: int | None
    rtk_timeout: int | None
    rtk_reliability: tuple[int, int] | None
    rtk_assists_ppp: bool | None
    rtcm_b1c_b2a: bool | None
    sbas_enabled: bool | None
    sbas_service: str | None
    mmp_enabled: bool | None
    anti_jam: str | None
    agnss_enabled: bool | None
    heading_reliability: int | None
    heading_mode: str | None
    dgps_timeout: int | None
    antenna_delta_hen: tuple[float, float, float] | None
    pps: str | None
    debug_level: int | None
    log_sequence: int | None
    command_checksums: bool | None
    ports: dict[str, int]
    entries: tuple[tuple[str, str], ...]

    def get(self, topic: str) -> tuple[str, ...]:
        """Return all configuration command strings matching ``topic``."""
        upper = topic.upper()
        return tuple(cmd for name, cmd in self.entries if name == upper)


def parse_configuration(messages: Sequence[Message]) -> ReceiverConfig:
    """Parse collected CONFIG reply sentences into a structured ReceiverConfig."""
    pairs = sorted(
        {
            (message.fields[0].strip(), message.fields[1].strip())
            for message in messages
            if isinstance(message, Sentence)
            and message.name == "CONFIG"
            and len(message.fields) >= 2
        }
    )
    antenna_power: str | None = None
    nmea_version: str | None = None
    sig_group: SignalGroup | None = None
    ppp_enabled: bool | None = None
    ppp_service: str | None = None
    ppp_timeout: int | None = None
    rtk_timeout: int | None = None
    rtk_rel: tuple[int, int] | None = None
    rtk_assists_ppp: bool | None = None
    rtcm_b1c_b2a: bool | None = None
    sbas_enabled: bool | None = None
    sbas_service: str | None = None
    mmp_enabled: bool | None = None
    anti_jam: str | None = None
    agnss_enabled: bool | None = None
    heading_rel: int | None = None
    heading_mode: str | None = None
    dgps_timeout: int | None = None
    delta_hen: tuple[float, float, float] | None = None
    pps: str | None = None
    debug_level: int | None = None
    log_seq: int | None = None
    cmd_format: bool | None = None
    ports: dict[str, int] = {}

    for topic, text in pairs:
        tokens = text.split()
        if len(tokens) < 3 or tokens[0] != "CONFIG":
            continue
        args = tokens[2:]
        match topic:
            case "ANTENNA" if args:
                antenna_power = args[0]
            case "NMEAVERSION" if args:
                nmea_version = args[0]
            case "SIGNALGROUP" if len(args) >= 1:
                master = int(args[0])
                slave = int(args[1]) if len(args) >= 2 else 0
                if 0 <= master <= 9 and 0 <= slave <= 9:
                    sig_group = SignalGroup(master, slave)
            case "PPP" if args:
                if args[0] == "TIMEOUT" and len(args) >= 2:
                    ppp_timeout = int(args[1])
                elif args[0] == "ENABLE":
                    ppp_enabled = True
                    ppp_service = args[1] if len(args) >= 2 else "AUTO"
                elif args[0] == "DISABLE":
                    ppp_enabled = False
            case "RTK" if args:
                if args[0] == "TIMEOUT" and len(args) >= 2:
                    rtk_timeout = int(args[1])
                elif args[0] == "RELIABILITY" and len(args) >= 3:
                    rtk_rel = (int(args[1]), int(args[2]))
            case "RTKASITPPP" if args:
                rtk_assists_ppp = args[0] == "ENABLE"
            case "RTCMB1CB2A" if args:
                rtcm_b1c_b2a = args[0] == "ENABLE"
            case "SBAS" if args:
                if args[0] == "ENABLE":
                    sbas_enabled = True
                    sbas_service = args[1] if len(args) >= 2 else "AUTO"
                elif args[0] == "DISABLE":
                    sbas_enabled = False
            case "MMP" if args:
                mmp_enabled = args[0] == "ENABLE"
            case "ANTIJAM" if args:
                anti_jam = " ".join(args)
            case "AGNSS" if args:
                agnss_enabled = args[0] == "ENABLE"
            case "HEADING" if args:
                if args[0] == "RELIABILITY" and len(args) >= 2:
                    heading_rel = int(args[1])
                else:
                    heading_mode = args[0]
            case "DGPS" if len(args) >= 2 and args[0] == "TIMEOUT":
                dgps_timeout = int(args[1])
            case "ANTENNADELTAHEN" if len(args) >= 3:
                delta_hen = (float(args[0]), float(args[1]), float(args[2]))
            case "PPS" if args:
                pps = " ".join(args)
            case "DEBUGLEVEL" if args:
                debug_level = int(args[0])
            case "LOGSEQ" if args:
                log_seq = int(args[0])
            case "CMDFORMAT" if args:
                cmd_format = int(args[0]) != 0
            case "COM1" | "COM2" | "COM3" if args:
                ports[topic] = int(args[-1])
            case _:
                pass

    return ReceiverConfig(
        antenna_power=antenna_power,
        nmea_version=nmea_version,
        signal_group=sig_group,
        ppp_enabled=ppp_enabled,
        ppp_service=ppp_service,
        ppp_timeout=ppp_timeout,
        rtk_timeout=rtk_timeout,
        rtk_reliability=rtk_rel,
        rtk_assists_ppp=rtk_assists_ppp,
        rtcm_b1c_b2a=rtcm_b1c_b2a,
        sbas_enabled=sbas_enabled,
        sbas_service=sbas_service,
        mmp_enabled=mmp_enabled,
        anti_jam=anti_jam,
        agnss_enabled=agnss_enabled,
        heading_reliability=heading_rel,
        heading_mode=heading_mode,
        dgps_timeout=dgps_timeout,
        antenna_delta_hen=delta_hen,
        pps=pps,
        debug_level=debug_level,
        log_sequence=log_seq,
        command_checksums=cmd_format,
        ports=ports,
        entries=tuple(pairs),
    )
