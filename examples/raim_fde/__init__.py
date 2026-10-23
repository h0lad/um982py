"""Runs residual chi-square RAIM with exclusion and protection levels."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

from examples.wls_position import (
    PositionSolution,
    RangeMeasurement,
    solve_position,
)
from um982py.geodesy import SPEED_OF_LIGHT, geodetic_from_ecef
from um982py.messages.enums import SatelliteSystem

DEFAULT_FALSE_ALARM_PROBABILITY = 1e-5
MINIMUM_FDE_SATELLITES = 5
STATE_SIZE = 4

__all__ = [
    "DEFAULT_FALSE_ALARM_PROBABILITY",
    "MINIMUM_FDE_SATELLITES",
    "RaimResult",
    "chi_square_threshold",
    "raim_fde",
]


@dataclass(frozen=True, slots=True)
class RaimResult:
    """Fault-detection verdict, exclusions and protection levels."""

    solution: PositionSolution
    alarm: bool
    test_statistic: float
    threshold: float
    excluded: tuple[tuple[SatelliteSystem, int], ...]
    hpl: float
    vpl: float
    integrity_passed: bool = False

    @property
    def exclusions(self) -> int:
        """Number of satellites removed by fault exclusion."""
        return len(self.excluded)


def chi_square_threshold(dof: int, probability: float) -> float:
    """Chi-square quantile by the Wilson-Hilferty approximation."""
    if dof < 1:
        raise ValueError("dof must be positive")
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be in 0..1")
    z_score = NormalDist().inv_cdf(probability)
    scaled = 2.0 / (9.0 * dof)
    return dof * (1.0 - scaled + z_score * math.sqrt(scaled)) ** 3


def raim_fde(
    measurements: Sequence[RangeMeasurement],
    initial: tuple[float, float, float, float],
    *,
    false_alarm_probability: float = DEFAULT_FALSE_ALARM_PROBABILITY,
    max_exclusions: int = 2,
) -> RaimResult:
    """Run residual chi-square RAIM with greedy exclusion and protection levels."""
    if len(measurements) < MINIMUM_FDE_SATELLITES:
        raise ValueError("at least five measurements are required")
    if max_exclusions < 0:
        raise ValueError("max_exclusions must not be negative")
    active = list(measurements)
    excluded: list[tuple[SatelliteSystem, int]] = []
    solution = solve_position(active, initial)
    if not solution.converged:
        raise ValueError("least-squares solution did not converge")
    first_statistic, first_threshold = _test_statistic(
        active, solution, false_alarm_probability
    )
    alarm = first_statistic > first_threshold
    final_statistic, final_threshold = first_statistic, first_threshold
    while (
        final_statistic > final_threshold
        and len(active) > MINIMUM_FDE_SATELLITES
        and len(excluded) < max_exclusions
    ):
        index = _largest_residual(active, solution)
        excluded.append((active[index].system, active[index].prn))
        active.pop(index)
        solution = solve_position(
            active, (solution.x, solution.y, solution.z, solution.clock_bias)
        )
        if not solution.converged:
            raise ValueError("least-squares solution did not converge")
        final_statistic, final_threshold = _test_statistic(
            active, solution, false_alarm_probability
        )
    hpl, vpl = _protection_levels(active, solution, final_threshold)
    passed = final_statistic <= final_threshold
    return RaimResult(
        solution=solution,
        alarm=alarm,
        test_statistic=first_statistic,
        threshold=first_threshold,
        excluded=tuple(excluded),
        hpl=hpl if passed else math.inf,
        vpl=vpl if passed else math.inf,
        integrity_passed=passed,
    )


def _test_statistic(
    measurements: Sequence[RangeMeasurement],
    solution: PositionSolution,
    false_alarm_probability: float,
) -> tuple[float, float]:
    residuals = _weighted_residuals(measurements, solution)
    dof = len(measurements) - STATE_SIZE
    if dof < 1:
        raise ValueError("at least five measurements are required")
    threshold = chi_square_threshold(dof, 1.0 - false_alarm_probability)
    return sum(residual * residual for residual in residuals), threshold


def _weighted_residuals(
    measurements: Sequence[RangeMeasurement], solution: PositionSolution
) -> list[float]:
    residuals = []
    for measurement in measurements:
        geometry = _geometry_row(measurement, solution)
        corrected = measurement.pseudorange + (
            SPEED_OF_LIGHT * measurement.satellite_clock
        )
        predicted = geometry[3] + solution.clock_bias * SPEED_OF_LIGHT
        residuals.append((predicted - corrected) / measurement.pseudorange_std)
    return residuals


def _largest_residual(
    measurements: Sequence[RangeMeasurement], solution: PositionSolution
) -> int:
    residuals = _weighted_residuals(measurements, solution)
    return max(range(len(residuals)), key=lambda index: abs(residuals[index]))


def _geometry_row(
    measurement: RangeMeasurement, solution: PositionSolution
) -> tuple[float, float, float, float]:
    delta_x = measurement.x - solution.x
    delta_y = measurement.y - solution.y
    delta_z = measurement.z - solution.z
    distance = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)
    return (
        -delta_x / distance,
        -delta_y / distance,
        -delta_z / distance,
        distance,
    )


def _design(
    measurements: Sequence[RangeMeasurement], solution: PositionSolution
) -> tuple[list[list[float]], list[float]]:
    design = []
    weights = []
    for measurement in measurements:
        unit_x, unit_y, unit_z, _ = _geometry_row(measurement, solution)
        design.append([unit_x, unit_y, unit_z, 1.0])
        weights.append(1.0 / measurement.pseudorange_std)
    return design, weights


def _inverse(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    augmented = [
        [*row, *(1.0 if row_index == column else 0.0 for column in range(size))]
        for row_index, row in enumerate(matrix)
    ]
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
    return [row[size:] for row in augmented]


def _protection_levels(
    measurements: Sequence[RangeMeasurement],
    solution: PositionSolution,
    threshold: float,
) -> tuple[float, float]:
    design, weights = _design(measurements, solution)
    normal = [[0.0] * STATE_SIZE for _ in range(STATE_SIZE)]
    for row, weight in zip(design, weights, strict=True):
        for i in range(STATE_SIZE):
            for j in range(STATE_SIZE):
                normal[i][j] += weight * weight * row[i] * row[j]
    inverse = _inverse(normal)
    coefficients = [
        [
            sum(inverse[i][j] * design[column][j] * weights[column] for j in range(4))
            for column in range(len(measurements))
        ]
        for i in range(STATE_SIZE)
    ]
    latitude, longitude = geodetic_from_ecef(solution.x, solution.y, solution.z)[:2]
    latitude_radians = math.radians(latitude)
    longitude_radians = math.radians(longitude)
    east = [
        -math.sin(longitude_radians) * coefficients[0][column]
        + math.cos(longitude_radians) * coefficients[1][column]
        for column in range(len(measurements))
    ]
    north = [
        -math.sin(latitude_radians)
        * math.cos(longitude_radians)
        * coefficients[0][column]
        - math.sin(latitude_radians)
        * math.sin(longitude_radians)
        * coefficients[1][column]
        + math.cos(latitude_radians) * coefficients[2][column]
        for column in range(len(measurements))
    ]
    up = [
        math.cos(latitude_radians)
        * math.cos(longitude_radians)
        * coefficients[0][column]
        + math.cos(latitude_radians)
        * math.sin(longitude_radians)
        * coefficients[1][column]
        + math.sin(latitude_radians) * coefficients[2][column]
        for column in range(len(measurements))
    ]
    horizontal_slopes = []
    vertical_slopes = []
    for column in range(len(measurements)):
        leverage = 1.0 - weights[column] * sum(
            design[column][row] * coefficients[row][column] for row in range(STATE_SIZE)
        )
        if leverage <= 1e-12:
            continue
        horizontal_slopes.append(
            math.hypot(east[column], north[column]) / math.sqrt(leverage)
        )
        vertical_slopes.append(abs(up[column]) / math.sqrt(leverage))
    root_threshold = math.sqrt(threshold)
    return (
        max(horizontal_slopes, default=math.inf) * root_threshold,
        max(vertical_slopes, default=math.inf) * root_threshold,
    )
