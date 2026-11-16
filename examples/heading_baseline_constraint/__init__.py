"""Heading and pitch estimation with a fixed baseline-length constraint.

The receiver reports an unconstrained baseline in BSLNENUHD.  When the physical
distance between the two antennas is known accurately, the estimated baseline
vector can be forced to that length.  This constraint removes one degree of
freedom and stabilises heading and pitch, especially for short baselines where
the up-component is noisy.

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

    The direction of the horizontal component is preserved, giving the same
    heading as the unconstrained baseline.  The pitch is recomputed from the
    rescaled up component over the requested length.
    """
    if length <= 0:
        raise ValueError("constrained baseline length must be positive")
    unconstrained = math.sqrt(east * east + north * north + up * up)
    if unconstrained <= 0:
        raise ValueError("unconstrained baseline has zero length")
    horizontal = math.sqrt(max(0.0, length * length - up * up))
    scale = horizontal / math.hypot(east, north) if (east or north) else 0.0
    constrained_east = east * scale
    constrained_north = north * scale
    constrained_up = max(-length, min(length, up))
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


def heading_residual(receiver_heading_deg: float, estimated_heading_deg: float) -> float:
    """Smallest signed difference between two headings, degrees."""
    delta = (receiver_heading_deg - estimated_heading_deg + 180.0) % 360.0 - 180.0
    return delta
