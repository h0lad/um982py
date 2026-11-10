"""Simple spherical guidance from a position to a waypoint."""

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, radians, sin

from um982py.geodesy import haversine_distance


@dataclass(frozen=True, slots=True)
class WaypointDirection:
    """Distance and true bearing; turn is clockwise from the supplied heading."""

    distance_m: float
    bearing_deg: float | None
    turn_deg: float | None


def waypoint_direction(
    latitude: float,
    longitude: float,
    target_latitude: float,
    target_longitude: float,
    *,
    heading_deg: float | None = None,
) -> WaypointDirection:
    """Calculate spherical distance and initial bearing; no route is planned.

    Bearing is undefined for coincident or antipodal points. Heading must be
    the vehicle's true heading, including any antenna mounting correction.
    """
    distance = haversine_distance(
        latitude, longitude, target_latitude, target_longitude
    )
    if heading_deg is not None and (
        not isfinite(heading_deg) or not 0 <= heading_deg < 360
    ):
        raise ValueError("heading_deg must be finite and in [0, 360)")
    phi1, phi2 = radians(latitude), radians(target_latitude)
    delta = radians(target_longitude - longitude)
    east = sin(delta) * cos(phi2)
    north = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(delta)
    bearing = degrees(atan2(east, north)) % 360 if hypot(east, north) > 1e-12 else None
    turn = (
        (bearing - heading_deg + 180) % 360 - 180
        if bearing is not None and heading_deg is not None
        else None
    )
    return WaypointDirection(distance, bearing, turn)
