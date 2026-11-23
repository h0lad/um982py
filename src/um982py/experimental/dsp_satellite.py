"""Per-satellite ECEF positions retained in UM982 DSP memory."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi, sqrt
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
    range_m: float | None
    """Satellite-clock-corrected line-of-sight range at the secondary time."""
    pseudorange_m: float | None
    """Raw pseudorange before the satellite clock correction, in metres."""
    approach_rate_mps: float | None
    """Negative range rate at the secondary time, positive when approaching."""
    elevation_rad: float | None
    """Elevation at the secondary time, in radians."""
    azimuth_rad: float | None
    """Azimuth at the secondary time, clockwise from north, in radians."""
    broadcast_ephemeris_age_s: int | None
    """Whole seconds between the secondary time and the broadcast ``t_oe``."""
    state_flags: int
    """Uninterpreted state flags."""
    glonass_frequency_channel: int | None
    """GLONASS FDMA channel decoded from the high byte of the state flags."""
    state_time_ms: int | None
    """State-update time in the constellation's native millisecond scale."""
    secondary_time_ms: int | None
    """Epoch of the range, pseudorange, rate and sky-geometry fields."""
    time_scale: str | None
    """GPST, GST, BDT, or GLOT. GLOT is milliseconds of day."""

    @property
    def radius_m(self) -> float:
        """Distance from the ECEF origin, useful as a broad validity check."""
        x, y, z = self.position_ecef_m
        return sqrt(x * x + y * y + z * z)

    @property
    def valid(self) -> bool:
        """Whether the firmware marks this state as usable."""
        return bool(self.state_flags & 1)

    @property
    def broadcast_path_selected(self) -> bool:
        """Whether the firmware selects the broadcast-ephemeris path."""
        return bool(self.state_flags & 2)

    @property
    def ionosphere_correction_selected(self) -> bool:
        """Whether the firmware applies the ionosphere/troposphere path."""
        return bool(self.state_flags & 4)

    @property
    def diagnostic_status_bit(self) -> bool:
        """Diagnostic status bit retained in the state flags."""
        return bool(self.state_flags & 0x10)


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

    Returned positions and velocities use metres and metres per second, and
    sky angles use radians. ``state_time_ms`` stamps the ECEF state, while
    ``secondary_time_ms`` stamps the range, geometry and ephemeris-age fields,
    which can be older. Records without a valid state flag or finite position
    are omitted.
    Captured state may be older than the receiver-wide GPS time. A window may
    be a shorter record-aligned prefix of a firmware table, as saved by older
    snapshots.
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
            range_values = unpack_from("<3d", table, offset + 0x30)
            range_data = (
                range_values
                if all(map(isfinite, range_values)) and range_values[0] > 0
                else None
            )
            sky_values = unpack_from("<2f", table, offset + 0x60)
            sky_data = (
                sky_values
                if all(map(isfinite, sky_values))
                and -pi / 2 <= sky_values[0] <= pi / 2
                and 0 <= sky_values[1] <= 2 * pi
                else None
            )
            state_time_ms, secondary_time_ms = unpack_from("<2I", table, offset + 0x68)
            ephemeris_age = unpack_from("<I", table, offset + 0x70)[0]
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
                    range_m=range_data[0] if range_data else None,
                    pseudorange_m=range_data[1] if range_data else None,
                    approach_rate_mps=range_data[2] if range_data else None,
                    elevation_rad=sky_data[0] if sky_data else None,
                    azimuth_rad=sky_data[1] if sky_data else None,
                    broadcast_ephemeris_age_s=(
                        ephemeris_age if constellation != "GLONASS" else None
                    ),
                    state_flags=state_flags,
                    glonass_frequency_channel=(
                        ((state_flags >> 8) & 0xFF) - 0x41
                        if constellation == "GLONASS" and state_flags & 0xFF00
                        else None
                    ),
                    state_time_ms=state_time_ms if valid_state_time else None,
                    secondary_time_ms=(
                        secondary_time_ms if valid_secondary_time else None
                    ),
                    time_scale=time_scale,
                )
            )
    return tuple(positions)
