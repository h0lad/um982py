"""Turns an east, north, up baseline into heading and pitch."""

from __future__ import annotations

import math
from dataclasses import dataclass

from um982py.messages import Record

FULL_TURN_DEGREES = 360.0


@dataclass(frozen=True, slots=True)
class Attitude:
    """Attitude of the baseline between the two antennas."""

    heading: float
    """Clockwise angle from true north, 0..360 degrees."""
    pitch: float
    """Angle above the local horizon, -90..90 degrees."""
    baseline_length: float
    """Baseline length in metres."""


def enu_length(east: float, north: float, up: float) -> float:
    """Length of an east, north, up vector in metres."""
    return math.sqrt(east * east + north * north + up * up)


def heading_degrees(east: float, north: float) -> float:
    """Clockwise angle from true north to the horizontal baseline, in degrees."""
    return math.degrees(math.atan2(east, north)) % FULL_TURN_DEGREES


def pitch_degrees(up: float, baseline_length: float) -> float:
    """Angle of the baseline above the horizontal plane, in degrees."""
    if baseline_length <= 0:
        raise ValueError("baseline length must be positive")
    return math.degrees(math.asin(max(-1.0, min(1.0, up / baseline_length))))


def attitude_from_enu(east: float, north: float, up: float) -> Attitude:
    """Build an attitude from an east, north, up baseline in metres."""
    length = enu_length(east, north, up)
    return Attitude(
        heading=heading_degrees(east, north),
        pitch=pitch_degrees(up, length),
        baseline_length=length,
    )


def enu_from_attitude(attitude: Attitude) -> tuple[float, float, float]:
    """Rebuild the east, north, up baseline in metres from an attitude."""
    horizontal = attitude.baseline_length * math.cos(math.radians(attitude.pitch))
    return (
        horizontal * math.sin(math.radians(attitude.heading)),
        horizontal * math.cos(math.radians(attitude.heading)),
        attitude.baseline_length * math.sin(math.radians(attitude.pitch)),
    )


def attitude_from_record(record: Record) -> Attitude:
    """Build an attitude from a BSLNENUHD record, whose components are ENU."""
    return attitude_from_enu(
        record.real("delta_1"), record.real("delta_2"), record.real("delta_3")
    )


def angular_rate(
    previous: Attitude, current: Attitude, interval_seconds: float
) -> float:
    """Heading rate in degrees per second across one wrapped heading interval."""
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("interval must be finite and positive")
    delta = (
        current.heading - previous.heading + FULL_TURN_DEGREES / 2
    ) % FULL_TURN_DEGREES - FULL_TURN_DEGREES / 2
    return delta / interval_seconds


@dataclass(frozen=True, slots=True)
class Torsion:
    """Relative rotation between two baselines that should share one frame."""

    heading_difference: float
    pitch_difference: float
    baseline_ratio: float
    rigid: bool


def torsion(
    reference: Attitude,
    other: Attitude,
    *,
    length_tolerance: float = 0.01,
) -> Torsion:
    """Twist of a second baseline relative to a reference on the same structure.

    A rigid body keeps its baseline length, so a length change outside
    ``length_tolerance`` marks the observation as non-rigid rather than as
    structural torsion.  Angles are compared after wrapping.
    """
    if reference.baseline_length <= 0 or other.baseline_length <= 0:
        raise ValueError("both baselines must have positive length")
    if length_tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    heading = (
        other.heading - reference.heading + FULL_TURN_DEGREES / 2
    ) % FULL_TURN_DEGREES - FULL_TURN_DEGREES / 2
    pitch = other.pitch - reference.pitch
    ratio = other.baseline_length / reference.baseline_length
    return Torsion(
        heading_difference=heading,
        pitch_difference=pitch,
        baseline_ratio=ratio,
        rigid=bool(abs(ratio - 1.0) <= length_tolerance),
    )


def swapped_attitude(attitude: Attitude) -> Attitude:
    """Attitude of the same baseline measured from the other antenna.

    The two antennas define one line, so reversing their roles adds half a turn
    to the heading and mirrors the pitch while the baseline length is
    unchanged.  Applying this twice returns the original attitude.
    """
    return Attitude(
        heading=(attitude.heading + FULL_TURN_DEGREES / 2) % FULL_TURN_DEGREES,
        pitch=-attitude.pitch,
        baseline_length=attitude.baseline_length,
    )
