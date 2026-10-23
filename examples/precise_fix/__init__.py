"""Accumulates a static occupation into one precise outlier-checked fix."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from um982py.capture import record_epoch
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef
from um982py.messages.enums import PositionType
from um982py.messages.record import Record

__all__ = [
    "RANK_NAMES",
    "Axis",
    "FixEstimate",
    "FixRejection",
    "FixSample",
    "axis_statistics",
    "clip_outliers",
    "effective_sample_size",
    "estimate",
    "fix_sample",
    "join_undulations",
    "marker_position",
    "position_rank",
    "reference_error",
]

RANK_NAMES: tuple[str, ...] = ("none", "single", "dgps", "float", "fixed")
"""Fix classes reported next to the average, weakest first."""

_RANKS: dict[PositionType, int] = {
    PositionType.NONE: 0,
    PositionType.FIXEDPOS: 0,
    PositionType.FIXEDHEIGHT: 0,
    PositionType.DOPPLER_VELOCITY: 0,
    PositionType.SINGLE: 1,
    PositionType.PSRDIFF: 2,
    PositionType.SBAS: 2,
    PositionType.L1_FLOAT: 3,
    PositionType.IONOFREE_FLOAT: 3,
    PositionType.NARROW_FLOAT: 3,
    PositionType.L1_INT: 4,
    PositionType.WIDE_INT: 4,
    PositionType.NARROW_INT: 4,
    PositionType.INS: 0,
    PositionType.INS_PSRSP: 1,
    PositionType.INS_PSRDIFF: 2,
    PositionType.INS_RTKFLOAT: 3,
    PositionType.INS_RTKFIXED: 4,
    PositionType.PPP_CONVERGING: 3,
    PositionType.PPP: 3,
    PositionType.PPP_AR: 4,
    PositionType.PPP_RTK: 4,
}


def position_rank(value: int) -> int:
    """Fix class of a native position type, from 0 (none) to 4 (fixed)."""
    try:
        kind = PositionType(value)
    except ValueError:
        return 0
    return _RANKS[kind]


@dataclass(frozen=True, slots=True)
class FixSample:
    """One static epoch in ECEF metres with its native quality indicators."""

    epoch: float
    x: float
    y: float
    z: float
    position_type: int
    solution_status: int
    satellites: int
    sigma_3d: float
    undulation: float | None = None
    correction_age_s: float | None = None

    @property
    def ecef(self) -> tuple[float, float, float]:
        """Position of this epoch in metres."""
        return (self.x, self.y, self.z)

    @property
    def rank(self) -> int:
        """Fix class of this epoch."""
        return position_rank(self.position_type)


@dataclass(frozen=True, slots=True)
class FixRejection:
    """One epoch kept out of the average, with the reason."""

    epoch: float
    reason: str


@dataclass(frozen=True, slots=True)
class Axis:
    """Mean, scatter and uncertainty of one local axis in metres."""

    mean: float
    std: float
    standard_error: float
    sigma95: float


@dataclass(frozen=True, slots=True)
class FixEstimate:
    """Averaged static position with scatter, uncertainty and convergence."""

    samples: int
    accepted: int
    rejected: int
    rejections: tuple[FixRejection, ...]
    ecef: tuple[float, float, float]
    latitude: float
    longitude: float
    height: float
    height_msl: float | None
    undulation: float | None
    east: Axis
    north: Axis
    up: Axis
    effective_samples_enu: tuple[float, float, float]
    converged: bool
    trace: tuple[float, ...]
    classes: tuple[tuple[str, int], ...]

    @property
    def epoch_horizontal_sigma(self) -> float:
        """Scatter of one epoch in the horizontal plane, metres."""
        return math.hypot(self.east.std, self.north.std)

    @property
    def epoch_vertical_sigma(self) -> float:
        """Scatter of one epoch in height, metres."""
        return self.up.std

    @property
    def horizontal_sigma(self) -> float:
        """Standard error of the averaged horizontal position, metres."""
        return math.hypot(self.east.standard_error, self.north.standard_error)

    @property
    def vertical_sigma(self) -> float:
        """Standard error of the averaged height, metres."""
        return self.up.standard_error

    @property
    def horizontal_95(self) -> float:
        """Conservative 95% radius bound under an independent Gaussian model."""
        return math.sqrt(-2.0 * math.log(0.05)) * self.horizontal_sigma

    @property
    def vertical_95(self) -> float:
        """Normal-approximation 95 percent interval of the averaged height."""
        return 1.96 * self.vertical_sigma

    @property
    def correlation_adjusted_horizontal_sigma(self) -> float:
        return math.hypot(
            self.east.std / math.sqrt(self.effective_samples_enu[0]),
            self.north.std / math.sqrt(self.effective_samples_enu[1]),
        )

    @property
    def correlation_adjusted_vertical_sigma(self) -> float:
        return self.up.std / math.sqrt(self.effective_samples_enu[2])


def fix_sample(record: Record, *, undulation: float | None = None) -> FixSample:
    """Turn one ``BESTXYZ`` record into a sample without re-projecting it."""
    if record.message is None:
        raise ValueError("BESTXYZ needs a receiver timestamp")
    sigma = math.sqrt(
        math.fsum(record.real(key) ** 2 for key in ("p_x_std", "p_y_std", "p_z_std"))
    )
    age = record.get("diff_age")
    return FixSample(
        epoch=record_epoch(record),
        x=record.real("p_x"),
        y=record.real("p_y"),
        z=record.real("p_z"),
        position_type=record.integer("pos_type"),
        solution_status=record.integer("p_sol_status"),
        satellites=record.integer("count_svs"),
        sigma_3d=sigma,
        undulation=undulation,
        correction_age_s=float(age) if isinstance(age, (int, float)) else None,
    )


def join_undulations(
    positions: Sequence[Record], geodetic: Iterable[Record]
) -> tuple[FixSample, ...]:
    """Attach the geoid separation of the matching epoch, when it is present."""
    undulations = {
        record_epoch(record): record.real("undulation")
        for record in geodetic
        if record.message is not None
    }
    return tuple(
        fix_sample(record, undulation=undulations.get(record_epoch(record)))
        for record in positions
    )


def axis_statistics(values: Sequence[float]) -> Axis:
    """Mean, sample deviation, standard error and 95 percent interval."""
    if not values:
        raise ValueError("at least one value is required")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("axis values must be finite")
    count = len(values)
    average = math.fsum(values) / count
    deviation = (
        math.sqrt(math.fsum((value - average) ** 2 for value in values) / (count - 1))
        if count > 1
        else math.nan
    )
    standard_error = deviation / math.sqrt(count)
    return Axis(average, deviation, standard_error, 1.96 * standard_error)


def effective_sample_size(values: Sequence[float]) -> float:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("at least one finite sample is required")
    count = len(values)
    if count < 3:
        return float(count)
    centre = math.fsum(values) / count
    residuals = [value - centre for value in values]
    variance = math.fsum(value * value for value in residuals)
    if variance == 0:
        return float(count)
    lag_one = math.fsum(a * b for a, b in pairwise(residuals)) / variance
    lag_one = min(max(lag_one, 0.0), (count - 1) / (count + 1))
    return max(1.0, count * (1 - lag_one) / (1 + lag_one))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _mad(values: Sequence[float]) -> float:
    centre = _median(values)
    return _median([abs(value - centre) for value in values])


def clip_outliers(
    samples: Sequence[FixSample], *, k: float = 4.0
) -> tuple[tuple[FixSample, ...], tuple[FixRejection, ...]]:
    """Drop epochs that deviate from a running median beyond ``k`` robust sigmas.

    The median and its scaled absolute deviation are used because a single
    gross outlier must not inflate the scale that is meant to detect it.  At
    least half of the epochs are always retained, so a noisy occupation still
    yields a fix instead of failing.  A non-positive ``k`` disables clipping.
    """
    if k < 0:
        raise ValueError("sigma_k must be non-negative")
    if k == 0:
        return tuple(samples), ()
    kept = list(samples)
    rejected: list[FixRejection] = []
    floor = max(3, len(samples) // 2)
    for _ in range(4):
        if len(kept) < 4:
            break
        axes = ("x", "y", "z")
        centres = [_median([getattr(sample, axis) for sample in kept]) for axis in axes]
        scales = [
            1.4826 * _mad([getattr(sample, axis) for sample in kept]) for axis in axes
        ]
        surviving = []
        for sample in kept:
            offsets = [
                abs(getattr(sample, axis) - centre) / max(scale, 1e-6)
                for axis, centre, scale in zip(axes, centres, scales, strict=True)
            ]
            if offsets and max(offsets) > k:
                rejected.append(FixRejection(sample.epoch, "outlier"))
            else:
                surviving.append(sample)
        if len(surviving) == len(kept):
            break
        if len(surviving) < floor:
            rejected = rejected[: len(rejected) - (len(kept) - len(surviving))]
            break
        kept = surviving
    return tuple(kept), tuple(rejected)


def _convergence_trace(
    samples: Sequence[FixSample], latitude: float, longitude: float
) -> tuple[float, ...]:
    """Running horizontal standard error, one entry per sample after the first."""
    means = [0.0, 0.0]
    squares = [0.0, 0.0]
    origin = samples[0].ecef
    trace = []
    for count, sample in enumerate(samples, start=1):
        east, north, _ = enu_from_ecef(
            sample.x - origin[0],
            sample.y - origin[1],
            sample.z - origin[2],
            latitude,
            longitude,
        )
        for index, value in enumerate((east, north)):
            delta = value - means[index]
            means[index] += delta / count
            squares[index] += delta * (value - means[index])
        errors = []
        for index in range(2):
            variance = max(0.0, squares[index] / (count - 1)) if count > 1 else 0.0
            errors.append(math.sqrt(variance / count))
        if count > 1:
            trace.append(math.hypot(*errors))
    return tuple(trace)


def estimate(
    samples: Sequence[FixSample],
    *,
    sigma_k: float = 4.0,
    minimum_samples: int = 30,
    target_horizontal_sigma: float = 0.01,
    target_vertical_sigma: float = 0.02,
) -> FixEstimate:
    """Average the whole occupation, rejecting only gross outliers.

    Every epoch that carries a computed solution enters the average, whatever
    its fix class, so a static occupation always yields a position.  The fix
    classes are reported next to the average, ``converged`` only states whether
    the requested epoch count and mean sigmas were reached, and only epochs that
    are gross outliers against the running median are dropped.
    """
    if not samples:
        raise ValueError("at least one sample is required")
    if not all(
        math.isfinite(value)
        for value in (sigma_k, target_horizontal_sigma, target_vertical_sigma)
    ):
        raise ValueError("estimate options must be finite")
    if sigma_k < 0:
        raise ValueError("sigma_k must be non-negative")
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be positive")
    if target_horizontal_sigma <= 0 or target_vertical_sigma <= 0:
        raise ValueError("target sigmas must be positive")
    computed = [
        sample
        for sample in samples
        if sample.solution_status == 0
        and all(math.isfinite(value) for value in sample.ecef)
    ]
    if not computed:
        raise ValueError("no sample carries a finite computed position")
    accepted, clipped = clip_outliers(computed, k=sigma_k)
    computed_epochs = {sample.epoch for sample in computed}
    rejections = list(clipped)
    rejections.extend(
        FixRejection(sample.epoch, "solution_not_computed")
        for sample in samples
        if sample.epoch not in computed_epochs
    )
    centre = tuple(
        math.fsum(getattr(sample, axis) for sample in accepted) / len(accepted)
        for axis in ("x", "y", "z")
    )
    latitude, longitude, height = geodetic_from_ecef(*centre)
    local = [
        enu_from_ecef(
            sample.x - centre[0],
            sample.y - centre[1],
            sample.z - centre[2],
            latitude,
            longitude,
        )
        for sample in accepted
    ]
    east, north, up = (
        axis_statistics([value[index] for value in local]) for index in range(3)
    )
    effective = tuple(
        effective_sample_size([value[index] for value in local]) for index in range(3)
    )
    adjusted_horizontal = math.hypot(
        east.std / math.sqrt(effective[0]), north.std / math.sqrt(effective[1])
    )
    adjusted_vertical = up.std / math.sqrt(effective[2])
    undulations = [
        sample.undulation for sample in accepted if sample.undulation is not None
    ]
    undulation = _median(undulations) if undulations else None
    converged = (
        len(accepted) >= minimum_samples
        and adjusted_horizontal <= target_horizontal_sigma
        and adjusted_vertical <= target_vertical_sigma
    )
    counts = Counter(sample.rank for sample in accepted)
    classes = tuple(
        (RANK_NAMES[rank], counts[rank]) for rank in sorted(counts) if counts[rank]
    )
    return FixEstimate(
        samples=len(samples),
        accepted=len(accepted),
        rejected=len(rejections),
        rejections=tuple(rejections),
        ecef=(centre[0], centre[1], centre[2]),
        latitude=latitude,
        longitude=longitude,
        height=height,
        height_msl=None if undulation is None else height - undulation,
        undulation=undulation,
        east=east,
        north=north,
        up=up,
        effective_samples_enu=(effective[0], effective[1], effective[2]),
        converged=converged,
        trace=_convergence_trace(accepted, latitude, longitude),
        classes=classes,
    )


def marker_position(
    ecef: tuple[float, float, float], antenna_height: float
) -> tuple[float, float, float]:
    """Move an antenna phase-centre position down to the marker, along the up axis."""
    if not math.isfinite(antenna_height):
        raise ValueError("antenna height must be finite")
    latitude, longitude, _ = geodetic_from_ecef(*ecef)
    phi, lam = math.radians(latitude), math.radians(longitude)
    up = (
        math.cos(phi) * math.cos(lam),
        math.cos(phi) * math.sin(lam),
        math.sin(phi),
    )
    return (
        ecef[0] - antenna_height * up[0],
        ecef[1] - antenna_height * up[1],
        ecef[2] - antenna_height * up[2],
    )


def reference_error(
    position: tuple[float, float, float], reference: tuple[float, float, float]
) -> tuple[float, float, float]:
    """East, north and up difference of a position against a known point."""
    latitude, longitude, _ = geodetic_from_ecef(*reference)
    return enu_from_ecef(
        position[0] - reference[0],
        position[1] - reference[1],
        position[2] - reference[2],
        latitude,
        longitude,
    )
