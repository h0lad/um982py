"""Turns baseline length and noise into heading and pitch uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from um982py.messages.record import Record

FULL_TURN_DEGREES = 360.0
RESOLVABLE_SIGMA_DEGREES = 90.0

__all__ = [
    "RESOLVABLE_SIGMA_DEGREES",
    "AttitudeBudget",
    "Baseline",
    "angle_sigma",
    "attitude_budget",
    "component_budget",
    "required_baseline",
]


@dataclass(frozen=True, slots=True)
class Baseline:
    """East, north, up baseline between the two antennas, in metres."""

    east: float
    north: float
    up: float

    @classmethod
    def from_record(cls, record: Record) -> Baseline:
        """Build the baseline from a decoded BSLNENUHD record."""
        return cls(
            east=record.real("delta_1"),
            north=record.real("delta_2"),
            up=record.real("delta_3"),
        )

    def negated(self) -> Baseline:
        """The same baseline measured from the other antenna input."""
        return Baseline(east=-self.east, north=-self.north, up=-self.up)

    @property
    def horizontal_length(self) -> float:
        """Length of the horizontal projection in metres."""
        return math.hypot(self.east, self.north)

    @property
    def length(self) -> float:
        """Full baseline length in metres."""
        return math.sqrt(self.east**2 + self.north**2 + self.up**2)

    @property
    def heading(self) -> float:
        """Clockwise angle from true north to the horizontal baseline, in degrees."""
        return math.degrees(math.atan2(self.east, self.north)) % FULL_TURN_DEGREES

    @property
    def pitch(self) -> float:
        """Angle of the baseline above the horizontal plane, in degrees."""
        if self.length <= 0:
            raise ValueError("baseline length must be positive")
        return math.degrees(math.asin(max(-1.0, min(1.0, self.up / self.length))))


@dataclass(frozen=True, slots=True)
class AttitudeBudget:
    """Heading and pitch of a baseline with their one-sigma accuracy."""

    heading: float
    pitch: float
    heading_sigma: float
    pitch_sigma: float
    baseline_length: float
    horizontal_length: float

    @property
    def resolvable(self) -> bool:
        """Whether the baseline noise leaves the heading meaningful."""
        return self.heading_sigma <= RESOLVABLE_SIGMA_DEGREES

    def with_offset(self, offset_heading: float) -> AttitudeBudget:
        """Budget in the frame the receiver reports after removing HEADINGOFFSET."""
        return replace(
            self, heading=(self.heading - offset_heading) % FULL_TURN_DEGREES
        )


def angle_sigma(sigma_length: float, baseline_length: float) -> float:
    """Angle standard deviation in radians from a length deviation."""
    if sigma_length < 0:
        raise ValueError("length deviation must be non-negative")
    if baseline_length <= 0:
        raise ValueError("baseline length must be positive")
    return sigma_length / baseline_length


def required_baseline(sigma_length: float, target_sigma: float) -> float:
    """Baseline length in metres that reaches a target angle deviation in degrees."""
    if target_sigma <= 0:
        raise ValueError("target deviation must be positive")
    return sigma_length / math.radians(target_sigma)


def attitude_budget(
    baseline: Baseline, latitude_std: float, height_std: float
) -> AttitudeBudget:
    """Budget from the position deviations in metres and the measured baseline."""
    return AttitudeBudget(
        heading=baseline.heading,
        pitch=baseline.pitch,
        heading_sigma=math.degrees(
            angle_sigma(latitude_std, baseline.horizontal_length)
        ),
        pitch_sigma=math.degrees(angle_sigma(height_std, baseline.length)),
        baseline_length=baseline.length,
        horizontal_length=baseline.horizontal_length,
    )


def component_budget(
    baseline: Baseline, east_std: float, north_std: float, up_std: float
) -> AttitudeBudget:
    """Propagate independent relative ENU component errors into attitude angles."""
    if any(
        not math.isfinite(value) or value < 0 for value in (east_std, north_std, up_std)
    ):
        raise ValueError("baseline standard deviations must be finite and non-negative")
    horizontal, length = baseline.horizontal_length, baseline.length
    if horizontal <= 0:
        raise ValueError("heading is undefined for a vertical or zero baseline")
    perpendicular = (
        math.hypot(baseline.north * east_std, baseline.east * north_std) / horizontal
    )
    radial = (
        math.hypot(baseline.east * east_std, baseline.north * north_std) / horizontal
    )
    pitch_std = math.hypot(baseline.up * radial, horizontal * up_std) / length**2
    return AttitudeBudget(
        baseline.heading,
        baseline.pitch,
        math.degrees(perpendicular / horizontal),
        math.degrees(pitch_std),
        length,
        horizontal,
    )
