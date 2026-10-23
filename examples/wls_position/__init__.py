"""Solves a position from pseudoranges with weighted least squares."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.geodesy import SPEED_OF_LIGHT, enu_from_ecef
from um982py.messages.enums import SatelliteSystem

MINIMUM_SATELLITES = 4
DEFAULT_TOLERANCE_METRES = 1e-3
DEFAULT_MAX_ITERATIONS = 20

__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_TOLERANCE_METRES",
    "MINIMUM_SATELLITES",
    "PositionError",
    "PositionSolution",
    "RangeMeasurement",
    "geodetic_position_error",
    "solve_position",
]


@dataclass(frozen=True, slots=True)
class RangeMeasurement:
    """One pseudorange and the satellite ECEF position that produced it."""

    system: SatelliteSystem
    prn: int
    x: float
    y: float
    z: float
    pseudorange: float
    pseudorange_std: float
    satellite_clock: float = 0.0
    """Satellite clock bias in seconds, to be added to the pseudorange."""


@dataclass(frozen=True, slots=True)
class PositionSolution:
    """Solved receiver ECEF position and clock bias."""

    x: float
    y: float
    z: float
    clock_bias: float
    """Receiver clock bias in seconds."""
    iterations: int
    residual_norms: tuple[float, ...]
    converged: bool


@dataclass(frozen=True, slots=True)
class PositionError:
    """Horizontal and vertical position error in metres."""

    horizontal: float
    vertical: float


def solve_position(
    measurements: Sequence[RangeMeasurement],
    initial: tuple[float, float, float, float],
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE_METRES,
) -> PositionSolution:
    """Gauss-Newton weighted least-squares solution for position and clock."""
    if len(measurements) < MINIMUM_SATELLITES:
        raise ValueError("at least four measurements are required")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    if not all(math.isfinite(value) for value in initial):
        raise ValueError("initial position and clock must be finite")
    for measurement in measurements:
        values = (
            measurement.x,
            measurement.y,
            measurement.z,
            measurement.pseudorange,
            measurement.pseudorange_std,
            measurement.satellite_clock,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("measurement values must be finite")
    if any(measurement.pseudorange_std <= 0 for measurement in measurements):
        raise ValueError("pseudorange_std must be positive")
    state = [initial[0], initial[1], initial[2], initial[3] * SPEED_OF_LIGHT]
    residual_norms = [_weighted_residual_norm(measurements, state)]
    converged = False
    iterations = 0
    for step_index in range(1, max_iterations + 1):
        iterations = step_index
        normal, right = _normal_equations(measurements, state)
        step = _solve(normal, right)
        state = [value + delta for value, delta in zip(state, step, strict=True)]
        residual_norms.append(_weighted_residual_norm(measurements, state))
        if math.sqrt(sum(delta * delta for delta in step)) < tolerance:
            converged = True
            break
    return PositionSolution(
        x=state[0],
        y=state[1],
        z=state[2],
        clock_bias=state[3] / SPEED_OF_LIGHT,
        iterations=iterations,
        residual_norms=tuple(residual_norms),
        converged=converged,
    )


def geodetic_position_error(
    solution: PositionSolution,
    latitude: float,
    longitude: float,
    x: float,
    y: float,
    z: float,
) -> PositionError:
    """Horizontal and vertical error against a known ECEF position."""
    east, north, up = enu_from_ecef(
        solution.x - x, solution.y - y, solution.z - z, latitude, longitude
    )
    return PositionError(horizontal=math.hypot(east, north), vertical=abs(up))


def _design_row(
    measurement: RangeMeasurement, state: Sequence[float]
) -> tuple[float, float, float, float, float]:
    delta_x = measurement.x - state[0]
    delta_y = measurement.y - state[1]
    delta_z = measurement.z - state[2]
    distance = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)
    if distance == 0:
        raise ValueError("satellite coincides with the receiver")
    return (
        -delta_x / distance,
        -delta_y / distance,
        -delta_z / distance,
        1.0,
        distance + state[3] - _clock_corrected_pseudorange(measurement),
    )


def _clock_corrected_pseudorange(measurement: RangeMeasurement) -> float:
    return measurement.pseudorange + SPEED_OF_LIGHT * measurement.satellite_clock


def _normal_equations(
    measurements: Sequence[RangeMeasurement], state: Sequence[float]
) -> tuple[list[list[float]], list[float]]:
    normal = [[0.0] * 4 for _ in range(4)]
    right = [0.0] * 4
    for measurement in measurements:
        row = _design_row(measurement, state)
        weight = 1.0 / measurement.pseudorange_std**2
        for i in range(4):
            right[i] -= weight * row[i] * row[4]
            for j in range(4):
                normal[i][j] += weight * row[i] * row[j]
    return normal, right


def _weighted_residual_norm(
    measurements: Sequence[RangeMeasurement], state: Sequence[float]
) -> float:
    return math.sqrt(
        sum(
            (_design_row(measurement, state)[4] / measurement.pseudorange_std) ** 2
            for measurement in measurements
        )
    )


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [[*row, vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("normal equations are singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        lead = augmented[column][column]
        augmented[column] = [value / lead for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    value - factor * lead_value
                    for value, lead_value in zip(
                        augmented[row], augmented[column], strict=True
                    )
                ]
    return [augmented[index][size] for index in range(size)]
