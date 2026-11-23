"""Per-satellite ECEF positions retained in UM982 DSP memory."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from struct import unpack_from
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from um982py.experimental.boot_memory import BootMemoryReader

__all__ = [
    "DSP_SATELLITE_STATE_FILES",
    "DspSatellitePosition",
    "extract_dsp_satellite_positions",
    "read_dsp_satellite_state_windows",
]

_RECORD_SIZE = 0x78
_VECTOR_SIZE = 3 * 8
_FLAGS_OFFSET = _RECORD_SIZE - 4
_GPS_WEEK_MS = 604_800_000
_GLONASS_DAY_MS = 86_400_000
_TIME_SCALES = {
    "GPS": "GPST",
    "GALILEO": "GST",
    "BEIDOU": "BDT",
    "GLONASS": "GLOT",
}

_SATELLITE_TABLES = (
    ("gps_state", 0x13D70528, 42, "GPS", 1, 1),
    ("galileo_state", 0x13D44840, 36, "GALILEO", 101, 1),
    ("beidou_state", 0x13D4CDF0, 63, "BEIDOU", 161, 1),
    ("glonass_state", 0x13D5FD18, 32, "GLONASS", 65, 65),
)

DSP_SATELLITE_STATE_FILES = tuple(name for name, *_ in _SATELLITE_TABLES)


@dataclass(frozen=True, slots=True)
class DspSatellitePosition:
    """One satellite position in ECEF coordinates."""

    constellation: str
    satellite_id: int
    receiver_id: int
    """Receiver-side identifier for this satellite."""
    position_ecef_m: tuple[float, float, float]
    """Satellite ECEF position in metres."""
    velocity_ecef_mps: tuple[float, float, float] | None
    """Satellite ECEF velocity in metres per second, when plausible."""
    state_flags: int
    """Uninterpreted state flags."""
    state_time_ms: int | None
    """State-update time in the constellation's native millisecond scale."""
    secondary_time_ms: int | None
    """Second native-system time tag. Its role is not assigned."""
    time_scale: str | None
    """GPST, GST, BDT, or GLOT. GLOT is milliseconds of day."""

    @property
    def radius_m(self) -> float:
        """Distance from the ECEF origin, useful as a broad validity check."""
        x, y, z = self.position_ecef_m
        return sqrt(x * x + y * y + z * z)


def read_dsp_satellite_state_windows(reader: BootMemoryReader) -> dict[str, bytes]:
    """Read the satellite state tables without exposing their memory layout."""
    return {
        name: reader.read_range(address, _RECORD_SIZE * count)
        for name, address, count, _, _, _ in _SATELLITE_TABLES
    }


def extract_dsp_satellite_positions(
    regions: Mapping[str, bytes],
) -> tuple[DspSatellitePosition, ...]:
    """Decode satellite ECEF states from captured memory windows.

    Returned positions and velocities use metres and metres per second. Time
    tags retain each constellation's native scale. Records without a valid
    state flag or finite position are omitted. Captured state may be older than
    the receiver-wide GPS time. A window may be a shorter record-aligned prefix
    of a firmware table, as saved by older snapshots.
    """
    positions = []
    for (
        name,
        _,
        count,
        constellation,
        first_receiver_id,
        first_satellite_id,
    ) in _SATELLITE_TABLES:
        raw = regions.get(name)
        if raw is None:
            continue
        expected_size = _RECORD_SIZE * count
        if not 0 < len(raw) <= expected_size or len(raw) % _RECORD_SIZE:
            raise ValueError(
                f"{name} contains {len(raw)} bytes, expected up to {expected_size}"
            )
        table = memoryview(raw)
        for index in range(len(raw) // _RECORD_SIZE):
            offset = index * _RECORD_SIZE
            position = unpack_from("<3d", table, offset)
            velocity_values = unpack_from("<3d", table, offset + _VECTOR_SIZE)
            if not all(map(isfinite, position)):
                continue
            state_flags = unpack_from("<I", table, offset + _FLAGS_OFFSET)[0]
            if state_flags & 1 == 0:
                continue
            velocity = velocity_values if all(map(isfinite, velocity_values)) else None
            state_time_ms, secondary_time_ms = unpack_from("<2I", table, offset + 0x68)
            time_limit = _GLONASS_DAY_MS if constellation == "GLONASS" else _GPS_WEEK_MS
            valid_state_time = 0 < state_time_ms < time_limit
            valid_secondary_time = 0 < secondary_time_ms < time_limit
            time_scale = (
                _TIME_SCALES[constellation]
                if valid_state_time or valid_secondary_time
                else None
            )
            positions.append(
                DspSatellitePosition(
                    constellation=constellation,
                    satellite_id=first_satellite_id + index,
                    receiver_id=first_receiver_id + index,
                    position_ecef_m=position,
                    velocity_ecef_mps=velocity,
                    state_flags=state_flags,
                    state_time_ms=state_time_ms if valid_state_time else None,
                    secondary_time_ms=(
                        secondary_time_ms if valid_secondary_time else None
                    ),
                    time_scale=time_scale,
                )
            )
    return tuple(positions)
