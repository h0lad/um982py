"""Maritime course-over-ground and heading cross-check.

For a marine vessel a single-antenna GNSS solution gives course over ground
(COG) from successive position differences.  A dual-antenna UM982 also gives
a true heading from the baseline between the two antennas.  Comparing the two
is useful for current/leeway estimation and for validating magnetometer-free
compass performance.

Reference
---------
Aykut, N. O. (2026). Experimental Assessment of Course over Ground and Heading
Determination for Marine Vessels Using Single- and Dual-Antenna GNSS
Positioning Solutions. Applied Sciences, 16(20), 10228.
doi:10.3390/app162010228
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.messages.enums import FixClass, SolutionStatus
from um982py.quality import classify, position_type_code, solution_status_code


@dataclass(frozen=True, slots=True)
class MaritimeEpoch:
    """One epoch of COG/heading comparison."""

    epoch: float | None
    latitude: float
    longitude: float
    speed_ms: float
    cog_deg: float | None
    heading_deg: float | None
    pitch_deg: float | None
    heading_minus_cog_deg: float | None
    interval_s: float | None = None
    unavailable_reason: str | None = None


def _wrap_heading_diff(a: float, b: float) -> float:
    """Smallest signed difference between two angles, -180..180."""
    return (a - b + 180.0) % 360.0 - 180.0


def cog_from_positions(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> float:
    """Course over ground from two WGS84 positions, clockwise from north."""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta_lon = math.radians(lon_b - lon_a)
    x = math.sin(delta_lon) * math.cos(phi_b)
    y = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(
        phi_b
    ) * math.cos(delta_lon)
    return math.degrees(math.atan2(x, y)) % 360.0


def compute_cog_heading(
    positions: Sequence[Record],
    headings: Sequence[Record],
    min_speed_ms: float = 0.5,
    *,
    max_gap_s: float = 5.0,
) -> list[MaritimeEpoch]:
    """Compare interval-average COG with heading at the interval's end epoch."""
    if (
        not math.isfinite(min_speed_ms)
        or min_speed_ms < 0
        or not math.isfinite(max_gap_s)
        or max_gap_s <= 0
    ):
        raise ValueError("speed must be nonnegative and max gap positive and finite")

    def timestamp(row: Record) -> float | None:
        try:
            epoch = gps_epoch(row)
        except (KeyError, TypeError, ValueError):
            return None
        return epoch if math.isfinite(epoch) else None

    heading_by_epoch: dict[float, Record] = {}
    for h in headings:
        stamp = timestamp(h)
        if stamp is not None:
            heading_by_epoch[stamp] = h

    def valid(row: Record) -> bool:
        try:
            return (
                solution_status_code(row) == SolutionStatus.SOL_COMPUTED
                and classify(position_type_code(row)) != FixClass.NONE
            )
        except (KeyError, ValueError):
            return False

    results: list[MaritimeEpoch] = []
    for prev, curr in itertools.pairwise(positions):
        epoch, previous_epoch = timestamp(curr), timestamp(prev)
        dt = (
            epoch - previous_epoch
            if epoch is not None and previous_epoch is not None
            else None
        )
        lat_a, lon_a = prev.real("lat"), prev.real("lon")
        lat_b, lon_b = curr.real("lat"), curr.real("lon")
        speed_ms = curr.real("hor_spd")
        reason = None
        if not valid(prev) or not valid(curr):
            reason = "invalid_position"
        elif dt is None:
            reason = "missing_epoch"
        elif not math.isfinite(dt) or dt <= 0:
            reason = "non_increasing_epoch"
        elif dt > max_gap_s:
            reason = "gap_exceeded"
        elif not all(
            math.isfinite(v) for v in (lat_a, lon_a, lat_b, lon_b, speed_ms)
        ) or not (
            -90 <= lat_a <= 90
            and -90 <= lat_b <= 90
            and -180 <= lon_a <= 180
            and -180 <= lon_b <= 180
        ):
            reason = "invalid_coordinates_or_speed"
        elif speed_ms < min_speed_ms:
            reason = "below_min_speed"
        elif lat_a == lat_b and (lon_b - lon_a) % 360 == 0:
            reason = "zero_displacement"
        cog = cog_from_positions(lat_a, lon_a, lat_b, lon_b) if reason is None else None

        heading_rec = heading_by_epoch.get(epoch) if epoch is not None else None
        heading = heading_rec.real("heading") if heading_rec is not None else None
        pitch = heading_rec.real("pitch") if heading_rec is not None else None
        diff = None
        if heading is not None and math.isfinite(heading) and cog is not None:
            diff = _wrap_heading_diff(heading, cog)

        results.append(
            MaritimeEpoch(
                epoch=epoch,
                latitude=lat_b,
                longitude=lon_b,
                speed_ms=speed_ms,
                cog_deg=cog,
                heading_deg=(
                    heading if heading is not None and math.isfinite(heading) else None
                ),
                pitch_deg=(
                    pitch if pitch is not None and math.isfinite(pitch) else None
                ),
                heading_minus_cog_deg=diff,
                interval_s=dt,
                unavailable_reason=reason,
            )
        )
    return results
