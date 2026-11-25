"""Receiver-wide diagnostics retained in UM982 DSP RAM."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from struct import unpack_from
from typing import TYPE_CHECKING

from um982py.experimental.baseband_reply import scan_notices

if TYPE_CHECKING:
    from collections.abc import Mapping

    from um982py.experimental.baseband_reply import BasebandNotice

__all__ = [
    "DSP_RECEIVER_MEMORY_WINDOWS",
    "DspClockState",
    "DspGpsEpoch",
    "DspGpsIonosphere",
    "DspNavPosition",
    "DspNavVelocity",
    "DspReceiverDiagnostics",
    "DspSensorAdc",
    "DspSystemClock",
    "extract_dsp_receiver_diagnostics",
]

_RF_AGC = 0x32CD7C
_SENSOR_ADC = 0x13D42388
_GPS_TIME = 0x13D443B0
_GPS_IONOSPHERE = 0x13D704C4
_SYSTEM_TIME_TABLE = 0x13D4421C
_SYSTEM_TIME = 0x13D44390
_SYSTEM_TIME_SIZE = 0x80
# Expected layout signature: five constellation slots giving the clock
# offset, time, week, an unidentified word and the constellation of each.
# Slot 1 is unused.
_SYSTEM_TIME_TABLE_WORDS = (
    0x13D44390, 0, 0x13D443A0, 0x13D443A8, 0x13D44398,
    0x13D443B0, 0, 0x13D443B8, 0x13D443BC, 0x13D443B4,
    0x13D443C0, 0, 0x13D443C8, 0x13D443CC, 0,
    0x13D443D0, 0, 0x13D443D8, 0x13D443DC, 0x13D443D4,
    0x305150, 0, 0x305155, 0x30515A, 0x30515F,
)  # fmt: skip
_SYSTEM_NAMES = {
    0x305150: "GPS",
    0x305155: "BEIDOU",
    0x30515A: "GALILEO",
    0x30515F: "GLONASS",
}
"""Constellation of each signature slot."""
_GLONASS_DAY = 0x13D443C4
_BIAS_VECTOR = 0x13D443F8
_BIAS_ORDER = ("BEIDOU", "GLONASS", "GALILEO")
_NOTICE_WINDOWS = (
    ("notice_402c00", 0x402C00, 0x2000),
    ("notice_404c00", 0x404C00, 0x2000),
    ("notice_406c08", 0x406C08, 0x3000),
    ("notice_409c08", 0x409C08, 0x3000),
)

DSP_RECEIVER_MEMORY_WINDOWS = (
    ("sensor_adc", _SENSOR_ADC, 12),
    ("gps_time", _GPS_TIME, 0x14),
    ("gps_ionosphere", _GPS_IONOSPHERE, 36),
    ("system_time_table", _SYSTEM_TIME_TABLE, 4 * len(_SYSTEM_TIME_TABLE_WORDS)),
    ("system_time", _SYSTEM_TIME, _SYSTEM_TIME_SIZE),
    *_NOTICE_WINDOWS,
)
"""Optional receiver-wide state read by the diagnostics example."""


@dataclass(frozen=True, slots=True)
class DspGpsEpoch:
    """Receiver-wide GPS time used to stamp DSP output."""

    week: int
    tow_ms: int


@dataclass(frozen=True, slots=True)
class DspGpsIonosphere:
    """The receiver's retained GPS broadcast ionosphere model."""

    alpha: tuple[float, ...]
    beta: tuple[float, ...]
    flags: tuple[int, int]
    """The two flag bytes in the order printed by GPSIONTOAP."""


@dataclass(frozen=True, slots=True)
class DspSystemClock:
    """One constellation's receiver clock offset in the DSP navigation solution."""

    constellation: str
    clock_offset_s: float
    """Receiver clock offset against this constellation's time.

    The sign is that of the RECTIME clock offset: pseudoranges follow
    P = rho - c * clock_offset_s, so RTKLIB's receiver clock bias is the
    negative of this value.
    """
    time_ms: int
    """GPS, BDT or GST time of week, or GLONASS time of day (UTC(SU) + 3 h)."""
    week: int | None
    """GPS, BDT or GST week number. None for GLONASS."""


@dataclass(frozen=True, slots=True)
class DspClockState:
    """Per-constellation receiver clocks of the DSP navigation solution.

    No receiver log reports these inter-system biases. A layout signature is
    checked first, so a different memory layout yields no state.
    """

    clocks: tuple[DspSystemClock, ...]
    """GPS first, then BeiDou, Galileo and GLONASS."""
    glonass_four_year_period: int | None
    """GLONASS N4: four-year interval number since 1996."""
    glonass_day: int | None
    """GLONASS NT: day number within the four-year interval."""
    bias_vector_consistent: bool
    """A separately stored bias vector equals the clock differences."""

    def inter_system_bias_s(self) -> dict[str, float]:
        """Each constellation's clock offset minus the GPS clock offset.

        RTKLIB's ``GLO-GPS``, ``GAL-GPS`` and ``BDS-GPS`` time offsets have
        the opposite sign.
        """
        gps = self.clocks[0].clock_offset_s
        return {
            clock.constellation: clock.clock_offset_s - gps for clock in self.clocks[1:]
        }


@dataclass(frozen=True, slots=True)
class DspSensorAdc:
    """Raw sensor ADC record from the DSP diagnostic stream."""

    channel: int
    value_1: int
    value_2: int


@dataclass(frozen=True, slots=True)
class DspNavPosition:
    """A NAVPOS diagnostic notice parsed into numeric fields."""

    tag: int
    mode: int
    position_type: int
    flag: int
    latitude_deg: float
    longitude_deg: float
    height_m: float
    x_m: float
    y_m: float
    z_m: float
    count: int


@dataclass(frozen=True, slots=True)
class DspNavVelocity:
    """A NAVVEL diagnostic notice parsed into numeric fields."""

    values: tuple[float, float, float, float, float]
    age: int
    trailing: float


def _parse_navpos(text: str) -> DspNavPosition | None:
    parts = text.strip().split(",")
    if len(parts) < 12 or parts[0] != "$NAVPOS":
        return None
    try:
        return DspNavPosition(
            int(parts[1]),
            int(parts[2]),
            int(parts[3]),
            int(parts[4]),
            float(parts[5]),
            float(parts[6]),
            float(parts[7]),
            float(parts[8]),
            float(parts[9]),
            float(parts[10]),
            int(parts[11]),
        )
    except ValueError:
        return None


def _parse_navvel(text: str) -> DspNavVelocity | None:
    parts = text.strip().split(",")
    if len(parts) < 8 or parts[0] != "$NAVVEL":
        return None
    try:
        values = tuple(float(part) for part in parts[1:6])
        return DspNavVelocity(
            (values[0], values[1], values[2], values[3], values[4]),
            int(parts[6]),
            float(parts[7]),
        )
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class DspReceiverDiagnostics:
    """Receiver-wide state and diagnostic messages retained at capture."""

    rf_agc_codes: tuple[int, ...] | None
    """Eight RF gain register codes in DSP order."""
    sensor_adc: DspSensorAdc | None
    gps_epoch: DspGpsEpoch | None
    gps_ionosphere: DspGpsIonosphere | None
    cached_notices: tuple[tuple[int, BasebandNotice], ...]
    """Diagnostic buffer base and parsed notice, in memory order within each buffer."""
    nav_positions: tuple[DspNavPosition, ...] = ()
    nav_velocities: tuple[DspNavVelocity, ...] = ()
    clock_state: DspClockState | None = None
    """Per-constellation clocks, when both system-time windows were captured."""


def _clock_state(table: bytes, time: bytes) -> DspClockState | None:
    words = len(_SYSTEM_TIME_TABLE_WORDS)
    if len(table) != 4 * words or len(time) != _SYSTEM_TIME_SIZE:
        return None
    if unpack_from(f"<{words}I", table) != _SYSTEM_TIME_TABLE_WORDS:
        return None

    def field(address: int, fmt: str) -> int | float:
        value: int | float = unpack_from(fmt, time, address - _SYSTEM_TIME)[0]
        return value

    clocks = []
    for slot in range(5):
        clock_address = _SYSTEM_TIME_TABLE_WORDS[slot]
        if clock_address == 0:
            continue
        offset = float(field(clock_address, "<d"))
        time_ms = int(field(_SYSTEM_TIME_TABLE_WORDS[5 + slot], "<I"))
        week_address = _SYSTEM_TIME_TABLE_WORDS[10 + slot]
        week = int(field(week_address, "<I")) if week_address else None
        if not isfinite(offset) or abs(offset) >= 1e-3 or time_ms >= 604_800_000:
            return None
        name = _SYSTEM_NAMES[_SYSTEM_TIME_TABLE_WORDS[20 + slot]]
        clocks.append(DspSystemClock(name, offset, time_ms, week))
    if not clocks or clocks[0].constellation != "GPS" or clocks[0].week == 0:
        return None
    glonass = int(field(_GLONASS_DAY, "<I"))
    period, day = glonass >> 16, glonass & 0xFFFF
    known = 0 < period < 32 and 0 < day <= 1461
    vector = unpack_from("<3d", time, _BIAS_VECTOR - _SYSTEM_TIME)
    offsets = {clock.constellation: clock.clock_offset_s for clock in clocks}
    consistent = all(
        name in offsets and abs(offsets[name] - offsets["GPS"] - bias) <= 1e-15
        for name, bias in zip(_BIAS_ORDER, vector, strict=True)
    )
    return DspClockState(
        clocks=tuple(clocks),
        glonass_four_year_period=period if known else None,
        glonass_day=day if known else None,
        bias_vector_consistent=consistent,
    )


def extract_dsp_receiver_diagnostics(
    regions: Mapping[str, tuple[int, bytes]],
) -> DspReceiverDiagnostics:
    """Recover receiver-wide diagnostics from captured RAM windows.

    Every input window is optional. Cached notices may predate the captured
    state and the physical order of buffers does not imply chronological order.
    """
    windows = tuple(regions.values())

    def read(address: int, size: int) -> bytes:
        for base, data in windows:
            offset = address - base
            if 0 <= offset <= len(data) - size:
                return data[offset : offset + size]
        return b""

    gains = read(_RF_AGC, 8)
    sensor = read(_SENSOR_ADC, 12)
    time = read(_GPS_TIME, 0x14)
    ion = read(_GPS_IONOSPHERE, 34)
    clock_state = _clock_state(
        read(_SYSTEM_TIME_TABLE, 4 * len(_SYSTEM_TIME_TABLE_WORDS)),
        read(_SYSTEM_TIME, _SYSTEM_TIME_SIZE),
    )
    adc = None
    if any(sensor):
        adc = DspSensorAdc(*unpack_from("<I2i", sensor))
    epoch = None
    if time:
        tow_ms = unpack_from("<I", time)[0]
        week = unpack_from("<I", time, 0x10)[0]
        if 0 < week <= 0xFFFF and tow_ms < 604_800_000:
            epoch = DspGpsEpoch(week, tow_ms)
    ionosphere = None
    if ion:
        coefficients = unpack_from("<8f", ion)
        if any(coefficients) and all(map(isfinite, coefficients)):
            ionosphere = DspGpsIonosphere(
                coefficients[:4], coefficients[4:], (ion[33], ion[32])
            )
    notices = tuple(
        (base, notice)
        for _, base, size in _NOTICE_WINDOWS
        for notice in scan_notices(read(base, size))
    )
    positions = []
    velocities = []
    for _, notice in notices:
        text = notice.raw.decode("latin1")
        position = _parse_navpos(text)
        if position is not None:
            positions.append(position)
        velocity = _parse_navvel(text)
        if velocity is not None:
            velocities.append(velocity)
    return DspReceiverDiagnostics(
        rf_agc_codes=tuple(gains) if any(gains) and max(gains) < 128 else None,
        sensor_adc=adc,
        gps_epoch=epoch,
        gps_ionosphere=ionosphere,
        cached_notices=notices,
        nav_positions=tuple(positions),
        nav_velocities=tuple(velocities),
        clock_state=clock_state,
    )
