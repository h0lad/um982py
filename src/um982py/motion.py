"""Ground motion and simple waypoint guidance from a receiver solution."""

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, radians, sin

from um982py.geodesy import haversine_distance
from um982py.messages.navigation import BestNavigation


@dataclass(frozen=True, slots=True)
class WaypointDirection:
    """Distance and true bearing. Turn is clockwise from the supplied heading."""

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
    """Calculate spherical distance and initial bearing. It does not plan a route.

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


@dataclass(frozen=True, slots=True)
class WaypointGuidance(WaypointDirection):
    """Spherical waypoint direction and ground-velocity component towards it."""

    closing_speed_m_s: float | None


@dataclass(frozen=True, slots=True)
class Motion:
    """Receiver ground motion and optional mounting-corrected true heading.

    Ground speed is not airspeed or speed through water. Heading is the antenna
    baseline direction adjusted by the caller's mounting offset and is not
    the course over ground. Missing or invalid measurements are None.
    """

    position: BestNavigation
    ground_speed_m_s: float | None
    course_deg: float | None
    vertical_speed_m_s: float | None
    heading_deg: float | None

    @property
    def velocity_epoch_gps_seconds(self) -> float | None:
        """Velocity epoch, adjusted for receiver-reported latency when available."""
        epoch = self.position.epoch_gps_seconds
        latency = self.position.velocity_latency_s
        if self.vertical_speed_m_s is None or epoch is None or latency is None:
            return None
        return epoch - latency

    @classmethod
    def from_navigation(
        cls,
        position: BestNavigation,
        *,
        heading_deg: float | None = None,
        heading_offset_deg: float = 0.0,
        min_course_speed_m_s: float = 0.5,
    ) -> Motion:
        """Interpret BESTNAV and, optionally, an epoch-matched baseline heading.

        Add ``heading_offset_deg`` to the baseline heading to obtain the
        vehicle's true heading. Course is omitted below the selected ground
        speed. The caller must verify that a supplied heading matches the epoch.
        """
        if not isfinite(heading_offset_deg):
            raise ValueError("heading offset must be finite")
        if not isfinite(min_course_speed_m_s) or min_course_speed_m_s < 0:
            raise ValueError("minimum course speed must be finite and non-negative")
        if heading_deg is not None and (
            not isfinite(heading_deg) or not 0 <= heading_deg <= 360
        ):
            raise ValueError("heading must be between 0 and 360 degrees")
        valid_velocity = position.valid and position.velocity_valid
        speed = (
            position.horizontal_speed
            if valid_velocity and position.horizontal_speed >= 0
            else None
        )
        course = (
            position.track % 360
            if speed is not None
            and speed > 0
            and speed >= min_course_speed_m_s
            and 0 <= position.track <= 360
            else None
        )
        heading = (
            (heading_deg + heading_offset_deg) % 360
            if position.valid and heading_deg is not None
            else None
        )
        return cls(
            position,
            speed,
            course,
            position.vertical_speed if valid_velocity else None,
            heading,
        )

    def waypoint(self, latitude: float, longitude: float) -> WaypointGuidance:
        """Return approximate distance, bearing, turn and closing speed.

        The destination and receiver must use the same reference frame. The
        calculation assumes a spherical Earth and does not plan a safe route.
        """
        if not self.position.valid:
            raise ValueError("waypoint guidance requires a valid position")
        direction = waypoint_direction(
            self.position.latitude,
            self.position.longitude,
            latitude,
            longitude,
            heading_deg=self.heading_deg,
        )
        closing = (
            self.ground_speed_m_s
            * cos(radians(self.course_deg - direction.bearing_deg))
            if self.ground_speed_m_s is not None
            and self.course_deg is not None
            and direction.bearing_deg is not None
            else None
        )
        return WaypointGuidance(
            direction.distance_m, direction.bearing_deg, direction.turn_deg, closing
        )
