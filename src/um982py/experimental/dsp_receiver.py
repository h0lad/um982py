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
    "DspGpsEpoch",
    "DspGpsIonosphere",
    "DspNavPosition",
    "DspNavVelocity",
    "DspReceiverDiagnostics",
    "DspSensorAdc",
    "extract_dsp_receiver_diagnostics",
]

_RF_AGC = 0x32CD7C
_SENSOR_ADC = 0x13D42388
_GPS_TIME = 0x13D443B0
_GPS_IONOSPHERE = 0x13D704C4
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
class DspSensorAdc:
    """Raw sensor ADC record as emitted by the baseband diagnostic."""

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
    )
