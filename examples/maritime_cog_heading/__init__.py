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

import math
from dataclasses import dataclass
from typing import Sequence

from um982py.messages import Record


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
    y = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(phi_b) * math.cos(delta_lon)
    return math.degrees(math.atan2(x, y)) % 360.0


def compute_cog_heading(
    positions: Sequence[Record],
    headings: Sequence[Record],
    min_speed_ms: float = 0.5,
) -> list[MaritimeEpoch]:
    """Match position and heading epochs and compute COG/heading differences."""
    heading_by_epoch: dict[float, Record] = {}
    for h in headings:
        from um982py.capture import record_epoch

        epoch = record_epoch(h)
        if epoch is not None:
            heading_by_epoch[epoch] = h

    results: list[MaritimeEpoch] = []
    for prev, curr in zip(positions, positions[1:]):
        from um982py.capture import record_epoch

        epoch = record_epoch(curr)
        lat_a = prev.real("lat")
        lon_a = prev.real("lon")
        lat_b = curr.real("lat")
        lon_b = curr.real("lon")
        speed_ms = curr.real("hor_spd")
        cog = None
        if speed_ms >= min_speed_ms and all(
            math.isfinite(v) for v in (lat_a, lon_a, lat_b, lon_b)
        ):
            cog = cog_from_positions(lat_a, lon_a, lat_b, lon_b)

        heading_rec = heading_by_epoch.get(epoch) if epoch is not None else None
        heading = heading_rec.real("heading") if heading_rec is not None else None
        pitch = heading_rec.real("pitch") if heading_rec is not None else None
        diff = None
        if heading is not None and cog is not None:
            diff = _wrap_heading_diff(heading, cog)

        results.append(
            MaritimeEpoch(
                epoch=epoch,
                latitude=lat_b,
                longitude=lon_b,
                speed_ms=speed_ms,
                cog_deg=cog,
                heading_deg=heading if heading is not None and math.isfinite(heading) else None,
                pitch_deg=pitch if pitch is not None and math.isfinite(pitch) else None,
                heading_minus_cog_deg=diff,
            )
        )
    return results
