"""Experimental GPS broadcast orbit, Doppler velocity and phase displacement models."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.experimental.orbit import EARTH_ROTATION_RATE, KeplerElements, orbit_state
from um982py.measurement import RangeSample
from um982py.messages import Record
from um982py.stats import Vector, dot, finite, least_squares, norm, rms, subtract, unit

C = 299792458.0


@dataclass(frozen=True, slots=True)
class RateMeasurement:
    """Range rate, satellite velocity and clock drift in metres per second."""

    prn: int
    line_of_sight: Vector
    satellite_velocity: Vector
    rate_mps: float
    satellite_clock_mps: float = 0.0
    sigma_mps: float = 1.0


@dataclass(frozen=True, slots=True)
class VelocitySolution:
    """ECEF velocity and receiver clock drift in metres per second."""

    velocity: Vector
    clock_mps: float
    residual_rms_mps: float
    satellites: int


def solve_velocity(measurements: Sequence[RateMeasurement]) -> VelocitySolution:
    """Solve range rate after removing satellite motion and satellite clock drift."""
    if len(measurements) < 4 or len({item.prn for item in measurements}) != len(
        measurements
    ):
        raise ValueError("at least four distinct GPS satellites are required")
    rows = []
    values = []
    for measurement in measurements:
        finite(*measurement.satellite_velocity, measurement.satellite_clock_mps)
        direction = unit(measurement.line_of_sight)
        rows.append([-component for component in direction] + [1.0])
        values.append(
            measurement.rate_mps
            - dot(direction, measurement.satellite_velocity)
            + measurement.satellite_clock_mps
        )
    solution = least_squares(rows, values, [item.sigma_mps for item in measurements])
    vx, vy, vz, clock = solution.parameters
    return VelocitySolution(
        (vx, vy, vz), clock, rms(solution.residuals), len(measurements)
    )


@dataclass(frozen=True, slots=True)
class PhaseDifference:
    """Carrier and stationary-observer geometric changes in metres."""

    prn: int
    line_of_sight: Vector
    phase_change_m: float
    geometric_change_m: float
    satellite_clock_change_m: float
    sigma_m: float = 0.01


@dataclass(frozen=True, slots=True)
class DisplacementSolution:
    """ECEF displacement and clock change over a continuous phase interval."""

    displacement_m: Vector
    velocity_mps: Vector
    clock_change_m: float
    residual_rms_m: float
    satellites: int


def solve_displacement(
    differences: Sequence[PhaseDifference], *, interval: float
) -> DisplacementSolution:
    """Solve first-order TDCP displacement after orbit and clock differencing."""
    finite(interval)
    if interval <= 0:
        raise ValueError("interval must be positive")
    if len(differences) < 4 or len({item.prn for item in differences}) != len(
        differences
    ):
        raise ValueError("at least four distinct GPS satellites are required")
    rows = []
    values = []
    for item in differences:
        rows.append([-value for value in unit(item.line_of_sight)] + [1.0])
        values.append(
            item.phase_change_m
            - item.geometric_change_m
            + item.satellite_clock_change_m
        )
    solution = least_squares(rows, values, [item.sigma_m for item in differences])
    dx, dy, dz, clock = solution.parameters
    return DisplacementSolution(
        (dx, dy, dz),
        (dx / interval, dy / interval, dz / interval),
        clock,
        rms(solution.residuals),
        len(differences),
    )


@dataclass(frozen=True, slots=True)
class OrbitPoint:
    """Satellite position rotated into the reception frame and clock in metres."""

    position: Vector
    clock_m: float


def choose_ephemeris(
    records: Sequence[Record], prn: int, epoch: float, *, max_age: float = 7200.0
) -> Record:
    """Choose a healthy GPS ephemeris by full week and bounded toe age."""
    choices = [
        record
        for record in records
        if record.integer("prn") == prn
        and record.integer("health") == 0
        and record.integer("iode1") == record.integer("iode2")
        and record.integer("iodc") & 255 == record.integer("iode1")
        and abs(epoch - (record.integer("week") * 604800 + record.real("toe")))
        <= max_age
    ]
    if not choices:
        raise ValueError(f"GPS {prn} has no healthy ephemeris within {max_age:g}s")
    return min(
        choices,
        key=lambda record: abs(
            epoch - (record.integer("week") * 604800 + record.real("toe"))
        ),
    )


def satellite_point(record: Record, epoch: float, code_m: float) -> OrbitPoint:
    """Apply transmit-time, satellite-clock and Earth-rotation corrections."""
    finite(epoch, code_m)
    if code_m <= 0:
        raise ValueError("pseudorange must be positive")
    elements = KeplerElements.from_record(record)
    toe = record.integer("week") * 604800 + elements.toe
    travel = code_m / C
    time = epoch - toe - travel
    state = orbit_state(elements, time)
    state = orbit_state(elements, time - state.clock_bias)
    angle = EARTH_ROTATION_RATE * travel
    cosine, sine = math.cos(angle), math.sin(angle)
    return OrbitPoint(
        (
            cosine * state.x + sine * state.y,
            -sine * state.x + cosine * state.y,
            state.z,
        ),
        C * (state.clock_bias + elements.tgd),
    )


def doppler_measurement(
    sample: RangeSample, ephemeris: Record, observer: Vector, *, sigma_mps: float = 0.5
) -> RateMeasurement:
    """Include apparent satellite motion and clock drift in the range-rate model."""
    step = 0.05
    point = satellite_point(ephemeris, sample.epoch, sample.code_m)
    before = satellite_point(
        ephemeris, sample.epoch - step, sample.code_m - sample.rate_mps * step
    )
    after = satellite_point(
        ephemeris, sample.epoch + step, sample.code_m + sample.rate_mps * step
    )
    delta = subtract(after.position, before.position)
    velocity = delta[0] / (2 * step), delta[1] / (2 * step), delta[2] / (2 * step)
    return RateMeasurement(
        sample.key.prn,
        unit(subtract(point.position, observer)),
        velocity,
        sample.rate_mps,
        (after.clock_m - before.clock_m) / (2 * step),
        sigma_mps,
    )


def phase_difference(
    before: RangeSample, after: RangeSample, ephemeris: Record, observer: Vector
) -> PhaseDifference:
    """Difference the same ephemeris across a continuous GPS phase arc."""
    first = satellite_point(ephemeris, before.epoch, before.code_m)
    last = satellite_point(ephemeris, after.epoch, after.code_m)
    return PhaseDifference(
        after.key.prn,
        unit(subtract(last.position, observer)),
        after.phase_m - before.phase_m,
        norm(subtract(last.position, observer))
        - norm(subtract(first.position, observer)),
        last.clock_m - first.clock_m,
        math.hypot(before.phase_std_m, after.phase_std_m),
    )
