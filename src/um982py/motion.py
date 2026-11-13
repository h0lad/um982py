"""Ground motion and simple waypoint guidance from a receiver solution."""

from dataclasses import dataclass
from math import cos, isfinite, radians

from um982py.messages.navigation import BestNavigation
from um982py.waypoint import WaypointDirection, waypoint_direction


@dataclass(frozen=True, slots=True)
class WaypointGuidance(WaypointDirection):
    """Spherical waypoint direction and ground-velocity component towards it."""

    closing_speed_m_s: float | None


@dataclass(frozen=True, slots=True)
class Motion:
    """Receiver ground motion and optional mounting-corrected true heading.

    Ground speed is not airspeed or speed through water. Heading is the antenna
    baseline direction adjusted by the caller's mounting offset; it is not the
    course over ground. Missing or invalid measurements are None.
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
    ) -> "Motion":
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
