"""Heading and pitch estimation with a fixed baseline-length constraint.

The receiver reports an unconstrained baseline in BSLNENUHD.  When the physical
distance between the two antennas is known, the estimated baseline vector can
be projected onto that length with equal component weights. This projection
preserves direction and cannot improve heading or pitch, and it is not an
observation-level constrained estimator.

Reference
---------
Ding, W., Sun, W., Yan, H., Li, W., & Jiang, Y. (2024). Low-cost dual-antenna
GNSS-based heading and pitch angles estimation considering baseline length
constraint. Measurement, 228, 115492. doi:10.1016/j.measurement.2024.115492
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from um982py.messages import Record


@dataclass(frozen=True, slots=True)
class ConstrainedAttitude:
    """Attitude that honours a fixed baseline length."""

    heading: float
    """Clockwise angle from true north, 0..360 degrees."""
    pitch: float
    """Angle above the local horizon, -90..90 degrees."""
    baseline_length: float
    """Requested constrained baseline length in metres."""
    unconstrained_length: float
    """Raw baseline length reported by the receiver in metres."""


def _heading_degrees(east: float, north: float) -> float:
    """Clockwise angle from true north, 0..360 degrees."""
    return math.degrees(math.atan2(east, north)) % 360.0


def constrain_to_length(
    east: float,
    north: float,
    up: float,
    length: float,
) -> ConstrainedAttitude:
    """Rescale ENU components so that their length equals *length*.

    All three components share one scale factor, the equal-weight projection
    onto the sphere of radius *length*. The baseline direction, and therefore
    heading and pitch, is preserved. Solving the horizontal length from the
    raw up component instead would let up noise beyond *length* collapse the
    horizontal vector and its heading.
    """
    if length <= 0:
        raise ValueError("constrained baseline length must be positive")
    unconstrained = math.sqrt(east * east + north * north + up * up)
    if unconstrained <= 0:
        raise ValueError("unconstrained baseline has zero length")
    scale = length / unconstrained
    constrained_east = east * scale
    constrained_north = north * scale
    constrained_up = up * scale
    heading = _heading_degrees(constrained_east, constrained_north)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, constrained_up / length))))
    return ConstrainedAttitude(
        heading=heading,
        pitch=pitch,
        baseline_length=length,
        unconstrained_length=unconstrained,
    )


def attitude_from_record(
    record: Record, baseline_length_m: float
) -> ConstrainedAttitude:
    """Build a constrained attitude from a BSLNENUHD record."""
    return constrain_to_length(
        record.real("delta_1"),
        record.real("delta_2"),
        record.real("delta_3"),
        baseline_length_m,
    )


def heading_residual(
    receiver_heading_deg: float, estimated_heading_deg: float
) -> float:
    """Smallest signed difference between two headings, degrees."""
    return (receiver_heading_deg - estimated_heading_deg + 180.0) % 360.0 - 180.0
