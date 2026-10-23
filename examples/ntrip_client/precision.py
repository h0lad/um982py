"""Choose a current receiver solution and summarize reported uncertainty."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from statistics import fmean, median

from examples.position_tracking import TrackPoint


@dataclass(slots=True)
class PrecisionMonitor:
    baseline: list[TrackPoint] = field(default_factory=list)
    corrected: list[TrackPoint] = field(default_factory=list)
    rtk: list[TrackPoint] = field(default_factory=list)

    def position(self, *, max_age_s: float = 8.0) -> TrackPoint | None:
        if self.corrected:
            selected = self.corrected[-1]
        elif self.baseline:
            selected = self.baseline[-1]
        else:
            selected = None
        if self.rtk:
            candidate = self.rtk[-1]
            if selected is None or candidate.timestamp - selected.timestamp > max_age_s:
                selected = candidate
            elif selected.timestamp - candidate.timestamp <= max_age_s:
                sigma = candidate.horizontal_sigma_m
                current = selected.horizontal_sigma_m
                if (
                    sigma is not None
                    and math.isfinite(sigma)
                    and (
                        current is None or not math.isfinite(current) or sigma < current
                    )
                ):
                    selected = candidate
        return selected


def _mean(values: list[float | None]) -> float | None:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(finite) if finite else None


def _metres(value: float | None) -> str:
    return f"{value:.3f} m" if value is not None else "unknown"


def precision_line(monitor: PrecisionMonitor) -> str:
    before, after = monitor.baseline, monitor.corrected
    if not after:
        return "Precision estimate: no SPPNAV fixes yet"
    horizontal = _mean([point.horizontal_sigma_m for point in after])
    if not before:
        return (
            f"Precision estimate: {len(after)} SPPNAV fixes; "
            f"mean per-fix horizontal sigma {_metres(horizontal)}; "
            "no baseline for comparison"
        )
    initial = _mean([point.horizontal_sigma_m for point in before])
    initial_height = _mean([point.height_sigma_m for point in before])
    final_height = _mean([point.height_sigma_m for point in after])
    ages = [
        point.correction_age_s
        for point in after
        if point.correction_age_s is not None
        and math.isfinite(point.correction_age_s)
        and point.correction_age_s > 0
    ]
    change = ""
    if initial is not None and horizontal is not None and initial > 0:
        difference = (initial - horizontal) / initial * 100
        direction = "lower" if difference >= 0 else "higher"
        change = f" ({abs(difference):.1f}% {direction})"
    parts = [
        f"Precision estimate: {len(before)} -> {len(after)} SPPNAV fixes",
        f"mean per-fix horizontal sigma {_metres(initial)} -> "
        f"{_metres(horizontal)}{change}",
        f"height sigma {_metres(initial_height)} -> {_metres(final_height)}",
        f"fixes {dict(Counter(p.position_type for p in before))} -> "
        f"{dict(Counter(p.position_type for p in after))}",
    ]
    if ages:
        parts.append(f"median correction age {median(ages):.1f} s")
    if any(point.position_type != "SINGLE" for point in before):
        parts.append("baseline already differential or augmented")
    return "; ".join(parts)
