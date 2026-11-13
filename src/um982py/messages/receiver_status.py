"""Interpret PPSSTATUS and SPOOFINFO status words.

The receiver reports raw masks as well as decoded flags. Unknown and reserved
bits are retained in the integer values so newer firmware can be inspected.
"""

from contextlib import suppress
from dataclasses import dataclass
from enum import IntFlag

from um982py.messages.enums import PositionType
from um982py.messages.record import Record


class SpoofNotice(IntFlag):
    POSITION = 1 << 0
    TIME = 1 << 1
    TRACKED_SATELLITES = 1 << 2
    SIGNAL_SOURCE = 1 << 3


class SpoofTimeNotice(IntFlag):
    GPS = 1 << 0
    BDS = 1 << 1
    GALILEO = 1 << 2
    GLONASS = 1 << 3


class SpoofSignal(IntFlag):
    BDS_B1I = 1 << 0
    BDS_B1C = 1 << 1
    BDS_B2I = 1 << 2
    BDS_B2A = 1 << 3
    BDS_B2B = 1 << 4
    BDS_B3I = 1 << 5
    GPS_L1CA = 1 << 8
    GPS_L1C = 1 << 9
    GPS_L2C = 1 << 10
    GPS_L5C = 1 << 11
    GPS_L6 = 1 << 12
    GLONASS_G1 = 1 << 15
    GLONASS_G2 = 1 << 16
    GLONASS_G3 = 1 << 17
    GALILEO_E1 = 1 << 20
    GALILEO_E5A = 1 << 21
    GALILEO_E5B = 1 << 22
    GALILEO_E6 = 1 << 23


def _unsigned(record: Record, key: str, bits: int) -> int:
    value = record.integer(key)
    if not 0 <= value < 1 << bits:
        raise ValueError(f"{key} must be an unsigned {bits}-bit integer")
    return value


def _satellites(mask: int) -> tuple[int, ...]:
    return tuple(index + 1 for index in range(64) if mask & (1 << index))


@dataclass(frozen=True, slots=True)
class SpoofInfo:
    """Spoofing notices and satellite masks, retaining reserved bits.

    Satellite numbers are the one-based positions in each constellation's
    mask, as stated in the receiver manual. They are not automatically
    converted to NMEA IDs. ``indicator`` retains unknown values; ``is_suspect``
    treats all nonzero values conservatively.
    """

    position_type: int | str
    indicator: int
    notices: SpoofNotice
    time_notices: SpoofTimeNotice
    signals: SpoofSignal
    gps_mask: int
    bds_mask: int
    galileo_mask: int
    glonass_mask: int

    @classmethod
    def from_record(cls, record: Record) -> "SpoofInfo":
        if record.name != "SPOOFINFO":
            raise ValueError("expected a SPOOFINFO record")
        position_type = record["position_type"]
        if isinstance(position_type, str):
            with suppress(KeyError):
                position_type = PositionType[position_type.upper()].value
        if not isinstance(position_type, (int, str)):
            raise ValueError("position_type must be a code or name")
        return cls(
            position_type,
            record.integer("spoof_indicator"),
            SpoofNotice(_unsigned(record, "spoof_notice_mask", 32)),
            SpoofTimeNotice(_unsigned(record, "time_notice_mask", 32)),
            SpoofSignal(_unsigned(record, "spoof_frequency_mask", 32)),
            _unsigned(record, "gps_satellite_notice_mask", 64),
            _unsigned(record, "bds_satellite_notice_mask", 64),
            _unsigned(record, "galileo_satellite_notice_mask", 64),
            _unsigned(record, "glonass_satellite_notice_mask", 64),
        )

    @property
    def position_type_label(self) -> str:
        if isinstance(self.position_type, str):
            return self.position_type
        try:
            return PositionType(self.position_type).name
        except ValueError:
            return str(self.position_type)

    @property
    def is_suspect(self) -> bool:
        """Treat unknown nonzero indicator values conservatively."""
        return self.indicator != 0

    @property
    def gps_satellites(self) -> tuple[int, ...]:
        return _satellites(self.gps_mask)

    @property
    def bds_satellites(self) -> tuple[int, ...]:
        return _satellites(self.bds_mask)

    @property
    def galileo_satellites(self) -> tuple[int, ...]:
        return _satellites(self.galileo_mask)

    @property
    def glonass_satellites(self) -> tuple[int, ...]:
        return _satellites(self.glonass_mask)


@dataclass(frozen=True, slots=True)
class PpsConfigInfo:
    """PPS configuration word; unknown configuration values remain numeric."""

    raw: int

    @property
    def mode(self) -> int:
        return self.raw & 0xF

    @property
    def falling_edge(self) -> bool:
        return bool(self.raw & 0x10)

    @property
    def gnss_reference(self) -> int:
        return (self.raw >> 5) & 0x7

    @property
    def interval(self) -> int:
        return (self.raw >> 16) & 0xFFFF


@dataclass(frozen=True, slots=True)
class PpsQuality:
    """Six four-bit internal position and constellation time quality codes."""

    raw: int

    @property
    def position(self) -> int:
        return self.raw & 0xF

    @property
    def gps(self) -> int:
        return (self.raw >> 4) & 0xF

    @property
    def bds(self) -> int:
        return (self.raw >> 8) & 0xF

    @property
    def galileo(self) -> int:
        return (self.raw >> 12) & 0xF

    @property
    def glonass(self) -> int:
        return (self.raw >> 16) & 0xF

    @property
    def irnss(self) -> int:
        return (self.raw >> 20) & 0xF


@dataclass(frozen=True, slots=True)
class PpsStatus:
    """PPS timing and bit fields reported by PPSSTATUS, table 7-152.

    Status 0 means no pulse, 1 means pulse accuracy is not guaranteed,
    2 indicates approximately 100-1000 ns, and 3 indicates better than
    100 ns. Other values are retained for forward compatibility.
    The observation offset is in hundredths of a nanosecond.
    """

    status: int
    gps_week: int
    milliseconds_of_week: int
    pulse_error_ns: int
    observation_offset_0_01_ns: int
    config: PpsConfigInfo
    register_status: int
    time_estimate_error: int
    quality: PpsQuality
    inner_status: int
    config_status: int
    stage: int

    @classmethod
    def from_record(cls, record: Record) -> "PpsStatus":
        if record.name != "PPSSTATUS":
            raise ValueError("expected a PPSSTATUS record")
        return cls(
            _unsigned(record, "status", 32),
            _unsigned(record, "gps_week", 32),
            _unsigned(record, "milliseconds_of_week", 32),
            record.integer("pulse_error_ns"),
            record.integer("observation_offset_0_01_ns"),
            PpsConfigInfo(_unsigned(record, "config_info", 32)),
            _unsigned(record, "register_status", 32),
            record.integer("time_estimate_error"),
            PpsQuality(_unsigned(record, "inner_quality", 32)),
            _unsigned(record, "pps_inner_status", 32),
            _unsigned(record, "pps_config_status", 32),
            _unsigned(record, "pps_stage", 32),
        )

    @property
    def control_register(self) -> int:
        return self.register_status & 0xF

    @property
    def pulse_control_register(self) -> int:
        return (self.register_status >> 4) & 0xF

    @property
    def inner_system(self) -> int:
        return (self.inner_status >> 8) & 0xFF

    @property
    def inner_control_flag(self) -> int:
        return (self.inner_status >> 16) & 0xFF

    @property
    def inner_state(self) -> int:
        return (self.inner_status >> 24) & 0xFF

    @property
    def current_pps_delay(self) -> int:
        return self.config_status & 0xFFFFF

    @property
    def time_reference(self) -> int:
        return (self.config_status >> 20) & 0xF

    @property
    def config_flag(self) -> int:
        return (self.config_status >> 24) & 0xFF

    @property
    def stable_count(self) -> int:
        return self.stage & 0xFF

    @property
    def switch_count(self) -> int:
        return (self.stage >> 8) & 0xFF

    @property
    def keep_count(self) -> int:
        return (self.stage >> 16) & 0xFF

    @property
    def hold_count(self) -> int:
        return (self.stage >> 24) & 0xFF
