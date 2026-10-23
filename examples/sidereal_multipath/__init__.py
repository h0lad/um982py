"""Evaluates held-out repeat-track residuals in sky bins."""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from um982py.measurement import SignalKey
from um982py.stats import correlation, finite, rms


@dataclass(frozen=True, slots=True)
class SkyResidual:
    """One detrended carrier-arc residual at a measured sky direction."""

    key: SignalKey
    epoch: float
    azimuth_deg: float
    elevation_deg: float
    residual_m: float


@dataclass(frozen=True, slots=True)
class Repeatability:
    """Out-of-sample performance for matching signal and sky cells."""

    training_samples: int
    validation_samples: int
    matched_samples: int
    coverage: float
    raw_rms_m: float | None
    corrected_rms_m: float | None
    correlation: float | None
    predictions: tuple[tuple[float, float, float], ...]


def evaluate_repeatability(
    training: Sequence[SkyResidual],
    validation: Sequence[SkyResidual],
    *,
    cell_degrees: float = 5.0,
    minimum_cell_samples: int = 3,
    minimum_separation: float = 72000.0,
) -> Repeatability:
    """Freeze a training-day map and score it without fitting validation residuals."""
    finite(cell_degrees, minimum_separation)
    if not 0 < cell_degrees <= 30 or minimum_cell_samples < 1 or minimum_separation < 0:
        raise ValueError(
            "cell size must be in (0,30], population positive and "
            "separation nonnegative"
        )
    if not training or not validation:
        raise ValueError("separate training and validation observations are required")
    if max(item.epoch for item in training) >= min(item.epoch for item in validation):
        raise ValueError("training and validation periods must not overlap")
    if (
        min(item.epoch for item in validation) - min(item.epoch for item in training)
        < minimum_separation
    ):
        raise ValueError("validation must be from a later repeat-day capture")

    def cell(item: SkyResidual) -> tuple[SignalKey, int, int]:
        finite(item.epoch, item.azimuth_deg, item.elevation_deg, item.residual_m)
        if not 0 <= item.elevation_deg <= 90:
            raise ValueError("elevation must be in 0..90 degrees")
        return (
            item.key,
            math.floor((item.azimuth_deg % 360) / cell_degrees),
            math.floor(item.elevation_deg / cell_degrees),
        )

    bins: dict[tuple[SignalKey, int, int], list[float]] = defaultdict(list)
    for item in training:
        bins[cell(item)].append(item.residual_m)
    model = {
        key: fmean(values)
        for key, values in bins.items()
        if len(values) >= minimum_cell_samples
    }
    predictions = tuple(
        (item.epoch, item.residual_m, model[key])
        for item in validation
        if (key := cell(item)) in model
    )
    raw = [item[1] for item in predictions]
    predicted = [item[2] for item in predictions]
    return Repeatability(
        len(training),
        len(validation),
        len(predictions),
        len(predictions) / len(validation),
        rms(raw) if raw else None,
        rms([a - b for a, b in zip(raw, predicted, strict=True)]) if raw else None,
        correlation(raw, predicted),
        predictions,
    )
