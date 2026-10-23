"""Averages ECEF fixes with weighted statistics until they converge."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.geodesy import enu_from_ecef, geodetic_from_ecef

__all__ = [
    "AxisStatistics",
    "SurveyCriteria",
    "SurveyResult",
    "SurveySample",
    "axis_statistics",
    "survey",
    "weighted_mean",
]


@dataclass(frozen=True, slots=True)
class SurveyCriteria:
    """Thresholds that decide when a survey-in has converged."""

    minimum_samples: int = 30
    horizontal_tolerance: float = 0.05
    vertical_tolerance: float = 0.10


@dataclass(frozen=True, slots=True)
class SurveySample:
    """One ECEF position in metres with its weight."""

    x: float
    y: float
    z: float
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class AxisStatistics:
    """Weighted mean, sample standard deviation and standard error in metres."""

    mean: float
    std: float
    standard_error: float


@dataclass(frozen=True, slots=True)
class SurveyResult:
    """Weighted survey position in ECEF and geodetic form."""

    count: int
    total_weight: float
    x: AxisStatistics
    y: AxisStatistics
    z: AxisStatistics
    east: AxisStatistics
    north: AxisStatistics
    up: AxisStatistics
    latitude: float
    longitude: float
    height: float
    converged: bool

    @property
    def ecef(self) -> tuple[float, float, float]:
        """Weighted mean ECEF position in metres."""
        return (self.x.mean, self.y.mean, self.z.mean)

    @property
    def horizontal_standard_error(self) -> float:
        """Combined standard error in the local horizontal plane, in metres."""
        return math.hypot(self.east.standard_error, self.north.standard_error)


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    """Weighted arithmetic mean of ``values``."""
    if len(values) != len(weights):
        raise ValueError("values and weights must have equal length")
    if not values:
        raise ValueError("at least one value is required")
    if any(not math.isfinite(weight) or weight < 0 for weight in weights):
        raise ValueError("weights must be finite and non-negative")
    total = math.fsum(weights)
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    return (
        math.fsum(weight * value for value, weight in zip(values, weights, strict=True))
        / total
    )


def axis_statistics(
    values: Sequence[float], weights: Sequence[float]
) -> AxisStatistics:
    """Weighted mean, sample standard deviation and standard error of one axis."""
    mean = weighted_mean(values, weights)
    if len(values) < 2:
        return AxisStatistics(mean, 0.0, 0.0)
    total = math.fsum(weights)
    squared_weights = math.fsum(weight * weight for weight in weights)
    reliability = total - squared_weights / total
    if reliability <= 0:
        return AxisStatistics(mean, 0.0, 0.0)
    scatter = math.fsum(
        weight * (value - mean) ** 2
        for value, weight in zip(values, weights, strict=True)
    )
    sigma = math.sqrt(scatter / reliability)
    effective = total * total / squared_weights
    return AxisStatistics(mean, sigma, sigma / math.sqrt(effective))


def survey(
    samples: Sequence[SurveySample], criteria: SurveyCriteria | None = None
) -> SurveyResult:
    """Average ECEF samples and report the geodetic position and convergence."""
    if not samples:
        raise ValueError("at least one sample is required")
    limits = SurveyCriteria() if criteria is None else criteria
    weights = [sample.weight for sample in samples]
    x = axis_statistics([sample.x for sample in samples], weights)
    y = axis_statistics([sample.y for sample in samples], weights)
    z = axis_statistics([sample.z for sample in samples], weights)
    latitude, longitude, height = geodetic_from_ecef(x.mean, y.mean, z.mean)
    local = [
        enu_from_ecef(
            sample.x - x.mean, sample.y - y.mean, sample.z - z.mean, latitude, longitude
        )
        for sample in samples
    ]
    east, north, up = (
        axis_statistics([value[index] for value in local], weights)
        for index in range(3)
    )
    converged = (
        len(samples) >= max(2, limits.minimum_samples)
        and math.hypot(east.standard_error, north.standard_error)
        <= limits.horizontal_tolerance
        and up.standard_error <= limits.vertical_tolerance
    )
    return SurveyResult(
        count=len(samples),
        total_weight=math.fsum(weights),
        x=x,
        y=y,
        z=z,
        east=east,
        north=north,
        up=up,
        latitude=latitude,
        longitude=longitude,
        height=height,
        converged=converged,
    )
