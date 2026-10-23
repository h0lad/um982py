"""Statistics, spectral and least-squares helpers."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.measurement import RangeSample

type Vector = tuple[float, float, float]

__all__ = [
    "LinearSolution",
    "allan_deviation",
    "correlation",
    "detrend",
    "dot",
    "finite",
    "fractional_frequency",
    "is_continuous",
    "least_squares",
    "lomb_scargle",
    "mean",
    "norm",
    "peaks",
    "percentile",
    "rms",
    "stddev",
    "subtract",
    "unit",
]


def mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean, or ``nan`` for an empty sequence."""
    return fmean(values) if values else math.nan


def stddev(values: Sequence[float], *, sample: bool = True) -> float:
    """Return standard deviation, or ``nan`` when there are too few values."""
    if not values or (sample and len(values) < 2):
        return math.nan
    average = mean(values)
    denominator = len(values) - 1 if sample else len(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / denominator)


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return a linearly interpolated percentile for a ``fraction`` between 0 and 1."""
    if not values:
        return math.nan
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be in 0..1")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def detrend(x: Sequence[float], y: Sequence[float], order: int = 1) -> list[float]:
    """Remove a least-squares polynomial of ``order`` from ``y``."""
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x) <= order:
        raise ValueError("not enough points for the requested polynomial order")
    if order < 0:
        raise ValueError("polynomial order must not be negative")
    centre = (min(x) + max(x)) / 2
    scale = max(abs(xi - centre) for xi in x) or 1.0
    basis = [
        [((xi - centre) / scale) ** power for power in range(order + 1)] for xi in x
    ]
    coefficients = _least_squares(basis, y)
    return [
        yi - sum(c * b for c, b in zip(coefficients, row, strict=True))
        for yi, row in zip(y, basis, strict=True)
    ]


def _least_squares(basis: list[list[float]], y: Sequence[float]) -> list[float]:
    size = len(basis[0])
    matrix = [[0.0] * size for _ in range(size)]
    vector = [0.0] * size
    for row, yi in zip(basis, y, strict=True):
        for i in range(size):
            vector[i] += row[i] * yi
            for j in range(size):
                matrix[i][j] += row[i] * row[j]
    return _solve(matrix, vector)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [[*row, vector[i]] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular system")
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
    return [augmented[i][size] for i in range(size)]


def lomb_scargle(
    samples: Sequence[float],
    values: Sequence[float],
    frequencies: Sequence[float],
) -> list[float]:
    """Classic Lomb-Scargle periodogram with unnormalised power."""
    if len(samples) != len(values):
        raise ValueError("samples and values must have equal length")
    if len(samples) < 3:
        raise ValueError("at least three samples are required")
    average = mean(values)
    centred = [value - average for value in values]
    powers = []
    for frequency in frequencies:
        omega = 2 * math.pi * frequency
        angle = [omega * t for t in samples]
        sin_sum = sum(math.sin(2 * a) for a in angle)
        cos_sum = sum(math.cos(2 * a) for a in angle)
        tau = math.atan2(sin_sum, cos_sum) / (2 * omega) if omega else 0.0
        cosine = sum(
            c * math.cos(omega * (t - tau))
            for c, t in zip(centred, samples, strict=True)
        )
        sine = sum(
            c * math.sin(omega * (t - tau))
            for c, t in zip(centred, samples, strict=True)
        )
        cos_norm = sum(math.cos(omega * (t - tau)) ** 2 for t in samples)
        sin_norm = sum(math.sin(omega * (t - tau)) ** 2 for t in samples)
        power = 0.0
        if cos_norm > 0:
            power += cosine**2 / cos_norm
        if sin_norm > 0:
            power += sine**2 / sin_norm
        powers.append(0.5 * power)
    return powers


def peaks(
    powers: Sequence[float], frequencies: Sequence[float]
) -> list[tuple[float, float]]:
    """Local maxima as ``(frequency, power)`` sorted by descending power."""
    found = [
        (frequencies[index], powers[index])
        for index in range(1, len(powers) - 1)
        if powers[index] > powers[index - 1] and powers[index] >= powers[index + 1]
    ]
    return sorted(found, key=lambda item: -item[1])


def fractional_frequency(phase: Sequence[float], tau0: float = 1.0) -> list[float]:
    """Convert a phase series in seconds to fractional frequency samples."""
    if not math.isfinite(tau0) or tau0 <= 0:
        raise ValueError("tau0 must be finite and positive")
    if not all(math.isfinite(value) for value in phase):
        raise ValueError("phase samples must be finite")
    if len(phase) < 2:
        return []
    return [(b - a) / tau0 for a, b in itertools.pairwise(phase)]


def allan_deviation(
    samples: Sequence[float], tau0: float = 1.0
) -> list[tuple[float, float]]:
    """Allan deviation of fractional-frequency samples at ``tau0`` seconds."""
    if not math.isfinite(tau0) or tau0 <= 0:
        raise ValueError("tau0 must be finite and positive")
    if not all(math.isfinite(value) for value in samples):
        raise ValueError("frequency samples must be finite")
    if len(samples) < 3:
        return []
    results = []
    factor = 1
    while factor <= (len(samples) - 1) // 2:
        averaged = [
            mean(samples[i : i + factor])
            for i in range(0, len(samples) - factor + 1, factor)
        ]
        differences = [averaged[i + 1] - averaged[i] for i in range(len(averaged) - 1)]
        if not differences:
            break
        variance = sum(d**2 for d in differences) / (2 * len(differences))
        results.append((factor * tau0, math.sqrt(variance)))
        factor *= 2
    return results


def finite(*values: float) -> None:
    """Reject nonfinite numerical inputs."""
    if not all(math.isfinite(value) for value in values):
        raise ValueError("all numerical inputs must be finite")


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean inner product of equal-length vectors."""
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def norm(a: Sequence[float]) -> float:
    """Euclidean norm."""
    return math.sqrt(dot(a, a))


def subtract(a: Vector, b: Vector) -> Vector:
    """Component differences of two vectors."""
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def unit(a: Vector) -> Vector:
    """Normalize a nonzero three-dimensional vector."""
    length = norm(a)
    if not math.isfinite(length) or length == 0:
        raise ValueError("vector must be finite and nonzero")
    return a[0] / length, a[1] / length, a[2] / length


def rms(values: Sequence[float]) -> float:
    """Root mean square of a nonempty finite series."""
    if not values:
        raise ValueError("at least one sample is required")
    finite(*values)
    return math.sqrt(fmean(value * value for value in values))


def correlation(
    a: Sequence[float], b: Sequence[float], *, minimum_samples: int = 3
) -> float | None:
    """Pearson correlation, or no estimate for a constant or short series.

    ``minimum_samples`` defaults to three because two paired samples are sufficient
    for the arithmetic but do not establish a robust statistical relationship.
    """
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    if len(a) != len(b):
        raise ValueError("paired series must have equal length")
    finite(*a, *b)
    if len(a) < minimum_samples:
        return None
    mean_a, mean_b = fmean(a), fmean(b)
    ac = [value - mean_a for value in a]
    bc = [value - mean_b for value in b]
    scale = norm(ac) * norm(bc)
    return max(-1.0, min(1.0, dot(ac, bc) / scale)) if scale else None


def is_continuous(
    before: RangeSample,
    after: RangeSample,
    *,
    max_gap: float = 2.0,
    phase_tolerance: float = 0.5,
) -> bool:
    """Check signal identity, cadence, lock progression and Doppler phase closure."""
    finite(max_gap, phase_tolerance)
    if max_gap <= 0 or phase_tolerance <= 0:
        raise ValueError("gap and phase tolerance must be positive")
    interval = after.epoch - before.epoch
    return (
        before.key == after.key
        and 0 < interval <= max_gap
        and after.lock_seconds >= before.lock_seconds + interval - 0.02
        and abs(
            after.phase_m
            - before.phase_m
            - (before.rate_mps + after.rate_mps) * interval / 2
        )
        <= phase_tolerance
    )


@dataclass(frozen=True, slots=True)
class LinearSolution:
    """Weighted least-squares parameters and residuals."""

    parameters: tuple[float, ...]
    residuals: tuple[float, ...]


def least_squares(
    rows: Sequence[Sequence[float]], values: Sequence[float], sigmas: Sequence[float]
) -> LinearSolution:
    """Solve a full-rank weighted system by modified Gram-Schmidt QR."""
    if not rows or len(rows) != len(values) or len(values) != len(sigmas):
        raise ValueError("design, observations and sigmas must have matching rows")
    columns = len(rows[0])
    if columns < 1 or len(rows) < columns or any(len(row) != columns for row in rows):
        raise ValueError("design matrix has incompatible dimensions")
    finite(*values, *sigmas, *(entry for row in rows for entry in row))
    if any(sigma <= 0 for sigma in sigmas):
        raise ValueError("measurement sigmas must be positive")
    weighted = [value / sigma for value, sigma in zip(values, sigmas, strict=True)]
    basis: list[list[float]] = []
    upper = [[0.0] * columns for _ in range(columns)]
    right: list[float] = []
    for column in range(columns):
        vector = [row[column] / sigma for row, sigma in zip(rows, sigmas, strict=True)]
        original_norm = norm(vector)
        for _ in range(2):
            for previous, q in enumerate(basis):
                projection = dot(q, vector)
                upper[previous][column] += projection
                vector = [v - projection * qi for v, qi in zip(vector, q, strict=True)]
        length = norm(vector)
        if length <= max(original_norm, 1e-30) * 1e-10:
            raise ValueError("satellite geometry is singular or ill-conditioned")
        upper[column][column] = length
        q = [value / length for value in vector]
        basis.append(q)
        right.append(dot(q, weighted))
    parameters = [0.0] * columns
    for i in reversed(range(columns)):
        parameters[i] = (
            right[i]
            - math.fsum(upper[i][j] * parameters[j] for j in range(i + 1, columns))
        ) / upper[i][i]
    return LinearSolution(
        tuple(parameters),
        tuple(
            value - dot(row, parameters)
            for row, value in zip(rows, values, strict=True)
        ),
    )
