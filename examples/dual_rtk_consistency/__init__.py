"""Dual-RTK consistency check for a UM982 dual-antenna receiver.

The master (ANT1) and slave (ANT2) position outputs can form a second
baseline estimate for comparison with UNIHEADING. These receiver solutions
may share measurements and errors; the comparison is not independent validation.

Reference
---------
Han, J., Park, C., Jang, Y. Y., et al. (2022). Development of a Moving Baseline
RTK/Motion Sensor-Integrated Positioning-Based Autonomous Driving Algorithm for
a Speed Sprayer. Sensors, 22(24), 9881. doi:10.3390/s22249881
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from um982py.geodesy import ecef_from_geodetic, enu_from_ecef, geodetic_from_ecef
from um982py.messages import Record
from um982py.messages.enums import SolutionStatus
from um982py.quality import FixClass, classify, position_type_code, solution_status_code


@dataclass(frozen=True, slots=True)
class ConsistencyEpoch:
    """One epoch of dual-RTK cross-check."""

    epoch: float | None
    master_ecef: tuple[float, float, float]
    slave_ecef: tuple[float, float, float]
    diff_ecef: tuple[float, float, float]
    diff_enu: tuple[float, float, float]
    diff_length_m: float
    receiver_heading_deg: float | None
    receiver_pitch_deg: float | None
    master_rtk_fixed: bool
    slave_rtk_fixed: bool


def _ecef_from_bestnav(record: Record) -> tuple[float, float, float] | None:
    """Return ECEF metres from a BESTNAV/BESTNAVH record, or None."""
    try:
        lat = record.real("lat")
        lon = record.real("lon")
        hgt = record.real("hgt")
        undulation = record.real("undulation")
        if not all(math.isfinite(v) for v in (lat, lon, hgt, undulation)):
            return None
        return ecef_from_geodetic(lat, lon, hgt + undulation)
    except (KeyError, ValueError):
        return None


def _is_rtk_fixed(record: Record) -> bool:
    """Require computed status and a documented fixed solution in either wire format."""
    try:
        return (
            solution_status_code(record) == SolutionStatus.SOL_COMPUTED
            and classify(position_type_code(record)) == FixClass.FIXED
        )
    except (KeyError, ValueError):
        return False


def baseline_from_positions(master: Record, slave: Record) -> ConsistencyEpoch | None:
    """Build a baseline from matched master and slave BESTNAV records."""
    master_ecef = _ecef_from_bestnav(master)
    slave_ecef = _ecef_from_bestnav(slave)
    if master_ecef is None or slave_ecef is None:
        return None
    try:
        if any(
            solution_status_code(row) != SolutionStatus.SOL_COMPUTED
            for row in (master, slave)
        ):
            return None
    except (KeyError, ValueError):
        return None
    diff = (
        slave_ecef[0] - master_ecef[0],
        slave_ecef[1] - master_ecef[1],
        slave_ecef[2] - master_ecef[2],
    )
    lat, lon, _ = geodetic_from_ecef(*master_ecef)
    enu = enu_from_ecef(*diff, lat, lon)
    length = math.sqrt(sum(c * c for c in diff))
    if length <= 0:
        return None
    return ConsistencyEpoch(
        epoch=None,
        master_ecef=master_ecef,
        slave_ecef=slave_ecef,
        diff_ecef=diff,
        diff_enu=enu,
        diff_length_m=length,
        receiver_heading_deg=None,
        receiver_pitch_deg=None,
        master_rtk_fixed=_is_rtk_fixed(master),
        slave_rtk_fixed=_is_rtk_fixed(slave),
    )


def heading_from_enu(east: float, north: float) -> float:
    """Clockwise heading from true north, 0..360 degrees."""
    return math.degrees(math.atan2(east, north)) % 360.0


def pitch_from_enu(up: float, length: float) -> float:
    """Pitch angle above the local horizon, degrees."""
    if length <= 0:
        return 0.0
    return math.degrees(math.asin(max(-1.0, min(1.0, up / length))))


def heading_difference(a_deg: float, b_deg: float) -> float:
    """Smallest signed difference between two headings, degrees."""
    return (a_deg - b_deg + 180.0) % 360.0 - 180.0
