"""Wait for an acceptable fix and measure a stationary point."""

import csv
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import fsum, isfinite, sqrt
from pathlib import Path
from re import fullmatch
from time import monotonic, sleep
from typing import Protocol

from um982py.commands import queries
from um982py.commands.core import Command
from um982py.errors import ResponseTimeout
from um982py.geodesy import ecef_from_geodetic, enu_from_ecef, geodetic_from_ecef
from um982py.messages.navigation import Fix


class _FixReader(Protocol):
    timeout: float

    def execute(self, command: Command[Fix], *, timeout: float) -> Fix: ...


def _options(timeout: float, interval: float, max_correction_age: float | None) -> None:
    for name, value in (("timeout", timeout), ("interval", interval)):
        if isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if max_correction_age is not None and (
        isinstance(max_correction_age, bool)
        or not isfinite(max_correction_age)
        or max_correction_age < 0
    ):
        raise ValueError("max_correction_age must be finite and non-negative")


def _acceptable(fix: Fix, rtk_fixed: bool, max_correction_age: float | None) -> bool:
    if not fix.valid or (rtk_fixed and not fix.rtk_fixed):
        return False
    if max_correction_age is not None:
        age = fix.differential_age
        return age is not None and isfinite(age) and 0 <= age <= max_correction_age
    return True


def _gga_seconds_of_day(value: str) -> Decimal | None:
    if fullmatch(r"[0-9]{6}(?:\.[0-9]+)?", value) is None:
        return None
    try:
        hour, minute, second = int(value[:2]), int(value[2:4]), Decimal(value[4:])
    except (ValueError, InvalidOperation):
        return None
    if hour >= 24 or minute >= 60 or second >= 60:
        return None
    return Decimal(hour * 3600 + minute * 60) + second


def wait_for_fix(
    receiver: _FixReader,
    *,
    timeout: float = 120,
    interval: float = 1,
    rtk_fixed: bool = False,
    max_correction_age: float | None = None,
    antenna: int = 1,
) -> Fix:
    """Poll until a GGA fix meets the requested conditions or the deadline expires.

    A correction-age limit rejects missing or invalid ages.
    """
    _options(timeout, interval, max_correction_age)
    command = queries.fix(antenna=antenna)
    deadline = monotonic() + timeout
    while (remaining := deadline - monotonic()) > 0:
        try:
            fix = receiver.execute(command, timeout=min(receiver.timeout, remaining))
        except ResponseTimeout:
            pass
        else:
            if _acceptable(fix, rtk_fixed, max_correction_age):
                return fix
        remaining = deadline - monotonic()
        if remaining > 0:
            sleep(min(interval, remaining))
    raise ResponseTimeout("No acceptable position fix before timeout")


@dataclass(frozen=True, slots=True)
class SurveyPoint:
    """Mean and sample scatter for a static antenna, in WGS 84 degrees and metres.

    Scatter measures repeatability, not absolute accuracy or uncertainty of the
    mean. Time-correlated errors and base-position errors are not removed.
    """

    latitude: float
    longitude: float
    ellipsoidal_height_m: float
    samples: int
    rejected: int
    horizontal_scatter_m: float
    vertical_scatter_m: float
    quality_counts: tuple[tuple[int, int], ...]

    def write_csv(self, path: str | Path) -> Path:
        """Write a single point to a new CSV file, including quality counts."""
        destination = Path(path)
        with destination.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "latitude",
                    "longitude",
                    "ellipsoidal_height_m",
                    "samples",
                    "rejected",
                    "horizontal_scatter_m",
                    "vertical_scatter_m",
                    "quality_counts",
                )
            )
            writer.writerow(
                (
                    self.latitude,
                    self.longitude,
                    self.ellipsoidal_height_m,
                    self.samples,
                    self.rejected,
                    self.horizontal_scatter_m,
                    self.vertical_scatter_m,
                    json.dumps(dict(self.quality_counts)),
                )
            )
        return destination


def survey_point(
    receiver: _FixReader,
    *,
    duration: float = 60,
    interval: float = 1,
    rtk_fixed: bool = False,
    max_correction_age: float | None = None,
    antenna: int = 1,
) -> SurveyPoint:
    """Average acceptable GGA fixes over a bounded stationary occupation.

    Ellipsoidal height requires both MSL height and geoid separation. The
    receiver's positions must be in WGS 84. The survey needs at least two fixes.
    """
    _options(duration, interval, max_correction_age)
    command = queries.fix(antenna=antenna)
    deadline = monotonic() + duration
    samples: list[tuple[float, float, float]] = []
    epochs: set[Decimal] = set()
    counts: Counter[int] = Counter()
    rejected = 0
    while (remaining := deadline - monotonic()) > 0:
        try:
            fix = receiver.execute(command, timeout=min(receiver.timeout, remaining))
        except ResponseTimeout:
            rejected += 1
        else:
            height = fix.ellipsoidal_height
            epoch = _gga_seconds_of_day(fix.utc)
            if (
                _acceptable(fix, rtk_fixed, max_correction_age)
                and fix.latitude is not None
                and fix.longitude is not None
                and height is not None
                and isfinite(height)
                and epoch is not None
                and epoch not in epochs
            ):
                samples.append(ecef_from_geodetic(fix.latitude, fix.longitude, height))
                epochs.add(epoch)
                counts[fix.quality] += 1
            else:
                rejected += 1
        remaining = deadline - monotonic()
        if remaining > 0:
            sleep(min(interval, remaining))
    if len(samples) < 2:
        raise ValueError(
            "survey needs at least two valid fixes with ellipsoidal height"
        )
    mean_ecef = tuple(
        fsum(sample[axis] for sample in samples) / len(samples) for axis in range(3)
    )
    latitude, longitude, height = geodetic_from_ecef(*mean_ecef)
    residuals = [
        enu_from_ecef(
            x - mean_ecef[0], y - mean_ecef[1], z - mean_ecef[2], latitude, longitude
        )
        for x, y, z in samples
    ]
    denominator = len(samples) - 1
    horizontal_scatter = sqrt(
        fsum(east * east + north * north for east, north, _ in residuals) / denominator
    )
    vertical_scatter = sqrt(fsum(up * up for _, _, up in residuals) / denominator)
    return SurveyPoint(
        latitude,
        longitude,
        height,
        len(samples),
        rejected,
        horizontal_scatter,
        vertical_scatter,
        tuple(sorted(counts.items())),
    )
