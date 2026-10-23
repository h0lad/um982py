"""Compares broadcast satellite states with independent precise products."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.stats import Vector, dot, finite, norm, subtract, unit


@dataclass(frozen=True, slots=True)
class OrbitDifference:
    """ECEF and radial, along-track, cross-track position differences in metres."""

    satellite: str
    epoch: float
    ecef_m: Vector
    radial_m: float
    along_m: float
    cross_m: float
    norm_m: float
    clock_difference_seconds: float | None


def compare_state(
    satellite: str,
    epoch: float,
    broadcast: Vector,
    reference: Vector,
    velocity_ecef: Vector,
    *,
    broadcast_clock: float,
    reference_clock: float | None,
) -> OrbitDifference:
    """Project state differences into an inertial-velocity-derived orbital basis."""
    finite(epoch, *broadcast, *reference, *velocity_ecef, broadcast_clock)
    if reference_clock is not None:
        finite(reference_clock)
    omega = 7.2921151467e-5
    velocity = (
        velocity_ecef[0] - omega * broadcast[1],
        velocity_ecef[1] + omega * broadcast[0],
        velocity_ecef[2],
    )
    radial = unit(broadcast)
    x, y, z = broadcast
    vx, vy, vz = velocity
    cross = unit((y * vz - z * vy, z * vx - x * vz, x * vy - y * vx))
    along = (
        cross[1] * radial[2] - cross[2] * radial[1],
        cross[2] * radial[0] - cross[0] * radial[2],
        cross[0] * radial[1] - cross[1] * radial[0],
    )
    delta = subtract(broadcast, reference)
    return OrbitDifference(
        satellite,
        epoch,
        delta,
        dot(delta, radial),
        dot(delta, along),
        dot(delta, cross),
        norm(delta),
        None if reference_clock is None else broadcast_clock - reference_clock,
    )


RADIAL_WEIGHT = 0.98
"""Radial weight of a broadcast orbit error in a single-frequency SISRE."""
ANGULAR_WEIGHT = 1.0 / 49.0
"""Along-track and cross-track weight of the same error."""
LIGHT_SPEED = 299_792_458.0


@dataclass(frozen=True, slots=True)
class SisreSummary:
    """Signal-in-space range error of one correction service over its samples."""

    samples: int
    rms_m: float
    maximum_m: float
    without_clock: int


def signal_in_space_range_error(
    difference: OrbitDifference,
    *,
    radial_weight: float = RADIAL_WEIGHT,
    angular_weight: float = ANGULAR_WEIGHT,
) -> float:
    """SISRE of one epoch, combining the projected orbit error with its clock.

    The textbook single-frequency form weights the radial orbit error together
    with the clock offset and de-weights the along-track and cross-track
    errors, so a large but harmless angular error does not dominate the score.
    An epoch without a reference clock cannot be scored and is rejected.
    """
    finite(difference.radial_m, difference.along_m, difference.cross_m)
    if difference.clock_difference_seconds is None:
        raise ValueError("a reference clock is required for SISRE")
    if radial_weight < 0 or angular_weight < 0:
        raise ValueError("weights must be non-negative")
    range_error = difference.radial_m - (
        difference.clock_difference_seconds * LIGHT_SPEED
    )
    angular = difference.along_m**2 + difference.cross_m**2
    return math.sqrt(
        radial_weight * range_error * range_error + angular_weight * angular
    )


def sisre_summary(differences: Sequence[OrbitDifference]) -> SisreSummary:
    """RMS and maximum SISRE of the epochs that carry a reference clock."""
    scores = [
        signal_in_space_range_error(difference)
        for difference in differences
        if difference.clock_difference_seconds is not None
    ]
    if not scores:
        return SisreSummary(0, math.nan, math.nan, len(differences))
    return SisreSummary(
        samples=len(scores),
        rms_m=math.sqrt(math.fsum(score * score for score in scores) / len(scores)),
        maximum_m=max(scores),
        without_clock=len(differences) - len(scores),
    )
