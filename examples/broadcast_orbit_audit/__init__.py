"""Compares broadcast satellite states with independent precise products."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.gnss import EARTH_ROTATION_RATE, SPEED_OF_LIGHT
from um982py.stats import Vector, cross, dot, finite, norm, subtract, unit


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
    omega = EARTH_ROTATION_RATE
    velocity = (
        velocity_ecef[0] - omega * broadcast[1],
        velocity_ecef[1] + omega * broadcast[0],
        velocity_ecef[2],
    )
    radial = unit(broadcast)
    normal = unit(cross(broadcast, velocity))
    along = cross(normal, radial)
    delta = subtract(broadcast, reference)
    return OrbitDifference(
        satellite,
        epoch,
        delta,
        dot(delta, radial),
        dot(delta, along),
        dot(delta, normal),
        norm(delta),
        None if reference_clock is None else broadcast_clock - reference_clock,
    )


RADIAL_WEIGHT = 0.98
"""GPS radial weight of a broadcast orbit error in global-average SISRE."""
ANGULAR_WEIGHT = 1.0 / 49.0
"""GPS along/cross-track weight (Montenbruck et al., 2018, table 1)."""


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
    with the clock offset. It gives less weight to along-track and cross-track
    errors, so a large but harmless angular error does not dominate the score.
    A score requires a reference clock. An epoch without one raises an error.
    """
    finite(difference.radial_m, difference.along_m, difference.cross_m)
    if difference.clock_difference_seconds is None:
        raise ValueError("a reference clock is required for SISRE")
    if radial_weight < 0 or angular_weight < 0:
        raise ValueError("weights must be non-negative")
    range_error = radial_weight * difference.radial_m - (
        difference.clock_difference_seconds * SPEED_OF_LIGHT
    )
    angular = difference.along_m**2 + difference.cross_m**2
    return math.sqrt(range_error * range_error + angular_weight * angular)


def sisre_summary(
    differences: Sequence[OrbitDifference],
    *,
    radial_weight: float = RADIAL_WEIGHT,
    angular_weight: float = ANGULAR_WEIGHT,
) -> SisreSummary:
    """RMS and maximum SISRE of the epochs that carry a reference clock."""
    scores = [
        signal_in_space_range_error(
            difference, radial_weight=radial_weight, angular_weight=angular_weight
        )
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
