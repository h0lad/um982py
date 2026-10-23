"""GPS-time SP3 products without implicit extrapolation."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

__all__ = ["PrecisePoint", "Sp3Product", "interpolate_sp3", "parse_sp3"]

GPS_ORIGIN = datetime(1980, 1, 6, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PrecisePoint:
    """Pairs satellite ECEF metres and clock seconds at absolute GPS seconds."""

    satellite: str
    epoch: float
    position: tuple[float, float, float]
    clock_seconds: float | None
    predicted_orbit: bool = False
    predicted_clock: bool = False
    clock_event: bool = False
    maneuver: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.epoch) or not all(
            math.isfinite(value) for value in self.position
        ):
            raise ValueError("precise point coordinates and epoch must be finite")
        if self.clock_seconds is not None and not math.isfinite(self.clock_seconds):
            raise ValueError("precise clock must be finite or absent")


@dataclass(frozen=True, slots=True)
class Sp3Product:
    """An SP3-c or SP3-d product with its time and coordinate metadata."""

    coordinate_system: str
    agency: str
    time_system: str
    points: tuple[PrecisePoint, ...]


def parse_sp3(text: str) -> Sp3Product:
    """Parse position records in an explicitly GPS-time SP3-c or SP3-d file."""
    lines = text.splitlines()
    if not lines or lines[0][:3] not in ("#cP", "#dP", "#cV", "#dV"):
        raise ValueError("expected an SP3-c or SP3-d header")
    if not any(line.strip() == "EOF" for line in lines):
        raise ValueError("SP3 product is incomplete: missing EOF")
    header = lines[0]
    time_system = next(
        (line[9:12].strip() for line in lines if line.startswith("%c")), ""
    )
    if time_system != "GPS":
        raise ValueError("only explicitly GPS-time SP3 products are supported")
    points = []
    epoch: float | None = None
    previous_epoch: float | None = None
    seen: set[tuple[str, float]] = set()
    for line in lines[1:]:
        if line.startswith("* "):
            fields = line[2:].split()
            if len(fields) != 6:
                raise ValueError("malformed SP3 epoch")
            year, month, day, hour, minute = map(int, fields[:5])
            seconds = float(fields[5])
            if not math.isfinite(seconds) or not 0 <= seconds < 60:
                raise ValueError("invalid GPS-time SP3 seconds")
            epoch = (
                datetime(year, month, day, hour, minute, tzinfo=UTC) - GPS_ORIGIN
            ).total_seconds() + seconds
            if previous_epoch is not None and epoch <= previous_epoch:
                raise ValueError("SP3 epochs must increase strictly")
            previous_epoch = epoch
        elif line.startswith("P"):
            if epoch is None or len(line) < 60:
                raise ValueError("SP3 position lacks an epoch or complete coordinates")
            satellite = line[1:4]
            if not satellite[0].isalpha() or not satellite[1:].isdigit():
                raise ValueError("invalid SP3 satellite identifier")
            key = satellite, epoch
            if key in seen:
                raise ValueError("duplicate SP3 satellite epoch")
            seen.add(key)
            x, y, z, clock = (
                float(line[start : start + 14]) for start in (4, 18, 32, 46)
            )
            if not all(math.isfinite(value) for value in (x, y, z, clock)):
                raise ValueError("SP3 values must be finite")
            if x == y == z == 0:
                continue
            # SP3 positions are in kilometres, and missing clocks use a sentinel.
            points.append(
                PrecisePoint(
                    satellite,
                    epoch,
                    (x * 1000, y * 1000, z * 1000),
                    None if clock >= 999999 else clock * 1e-6,
                    len(line) > 79 and line[79] == "P",
                    len(line) > 75 and line[75] == "P",
                    len(line) > 74 and line[74] == "E",
                    len(line) > 78 and line[78] == "M",
                )
            )
    if not points:
        raise ValueError("SP3 contains no valid satellite positions")
    return Sp3Product(
        header[46:51].strip(), header[56:60].strip(), time_system, tuple(points)
    )


def interpolate_sp3(
    points: Sequence[PrecisePoint],
    epoch: float,
    *,
    order: int = 8,
    max_gap: float = 901.0,
) -> PrecisePoint:
    """Interpolate one satellite locally and interpolate its clock linearly."""
    if (
        not math.isfinite(epoch)
        or not math.isfinite(max_gap)
        or max_gap <= 0
        or not 1 <= order <= 12
    ):
        raise ValueError("finite epoch, positive gap and order in 1..12 are required")
    series = sorted(points, key=lambda point: point.epoch)
    if not series or len({point.satellite for point in series}) != 1:
        raise ValueError("interpolation requires one satellite")
    if any(b.epoch <= a.epoch for a, b in pairwise(series)):
        raise ValueError("duplicate precise epochs")
    for point in series:
        if point.epoch == epoch:
            return point
    if not series[0].epoch < epoch < series[-1].epoch:
        raise ValueError("precise orbit extrapolation is not allowed")
    right = next(i for i, point in enumerate(series) if point.epoch > epoch)
    count = min(order + 1, len(series))
    # Centre the interpolation window where possible, without crossing the ends.
    start = min(max(right - count // 2, 0), len(series) - count)
    window = series[start : start + count]
    if any(b.epoch - a.epoch > max_gap for a, b in pairwise(window)):
        raise ValueError("precise orbit interpolation crosses a data gap")
    if any(point.maneuver for point in window):
        raise ValueError("precise orbit interpolation crosses a maneuver flag")
    weights = [
        math.prod(
            (epoch - other.epoch) / (point.epoch - other.epoch)
            for j, other in enumerate(window)
            if i != j
        )
        for i, point in enumerate(window)
    ]
    position = tuple(
        math.fsum(
            weight * point.position[axis]
            for weight, point in zip(weights, window, strict=True)
        )
        for axis in range(3)
    )
    before, after = series[right - 1], series[right]
    clock = None
    if (
        before.clock_seconds is not None
        and after.clock_seconds is not None
        and not after.clock_event
    ):
        fraction = (epoch - before.epoch) / (after.epoch - before.epoch)
        clock = before.clock_seconds + fraction * (
            after.clock_seconds - before.clock_seconds
        )
    return PrecisePoint(
        series[0].satellite,
        epoch,
        (position[0], position[1], position[2]),
        clock,
        any(point.predicted_orbit for point in window),
        before.predicted_clock or after.predicted_clock,
        False,
        False,
    )
