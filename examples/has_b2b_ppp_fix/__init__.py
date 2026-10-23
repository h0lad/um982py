"""Averages Galileo E6-HAS and BeiDou B2b-PPP fixes with a divergence audit."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.capture import record_epoch
from um982py.geodesy import ecef_from_geodetic, enu_from_ecef, geodetic_from_ecef
from um982py.messages.enums import PositionType
from um982py.messages.record import Record

__all__ = [
    "Convergence",
    "DivergenceTally",
    "MeanFix",
    "PppEpoch",
    "PrecisionStatistics",
    "convergence",
    "divergence_tally",
    "format_position",
    "format_precision",
    "mean_fix",
    "position_label",
    "ppp_epochs",
    "precision_statistics",
    "xyz_fallback",
]

_PPP_TYPES = frozenset(
    {
        PositionType.PPP_CONVERGING,
        PositionType.PPP,
        PositionType.PPP_AR,
        PositionType.PPP_RTK,
    }
)

_RAYLEIGH_P95_OVER_SCATTER = 1.7308


@dataclass(frozen=True, slots=True)
class PppEpoch:
    """One PPPNAV fix with its native receiver uncertainty."""

    epoch: float
    latitude: float
    longitude: float
    height: float
    """Ellipsoidal height in metres."""
    position_type: int
    solution_status: int
    latitude_sigma: float | None
    longitude_sigma: float | None
    height_sigma: float | None
    satellites: int
    solution_satellites: int | None
    correction_age: float | None

    @property
    def horizontal_sigma(self) -> float | None:
        """Combined horizontal uncertainty in metres, when reported."""
        if self.latitude_sigma is None or self.longitude_sigma is None:
            return None
        return math.hypot(self.latitude_sigma, self.longitude_sigma)

    @property
    def is_ppp(self) -> bool:
        """True for a computed converging or converged PPP solution."""
        if self.solution_status != 0:
            return False
        try:
            return PositionType(self.position_type) in _PPP_TYPES
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class Convergence:
    """PPP convergence state from the first to the last epoch."""

    total: int
    ppp: int
    converged_fix: int
    first_horizontal_sigma: float | None
    last_horizontal_sigma: float | None
    improvement: float | None
    converged: bool
    classes: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class MeanFix:
    """Averaged ultra-precise position with scatter and receiver uncertainty."""

    latitude: float
    longitude: float
    height: float
    ecef: tuple[float, float, float]
    horizontal_scatter: float
    vertical_scatter: float
    horizontal_sigma: float | None
    vertical_sigma: float | None
    epochs: int
    ppp_epochs: int
    source: str


@dataclass(frozen=True, slots=True)
class DivergenceTally:
    """Code-carrier divergence audit across every tracked signal."""

    signals: int
    samples: int
    resets: int
    exceeds: int
    worst_filtered_mps: float | None
    worst_signal: str | None


@dataclass(frozen=True, slots=True)
class PrecisionStatistics:
    """Repeatability of a static occupation about its own mean position."""

    epochs: int
    span_seconds: float
    east_std: float
    north_std: float
    up_std: float
    horizontal_scatter: float
    vertical_scatter: float
    mean_horizontal_sigma: float | None
    min_horizontal_sigma: float | None
    max_horizontal_sigma: float | None
    mean_vertical_sigma: float | None
    radius_p95: float
    improvement: float | None


def position_label(value: int) -> str:
    """Native position-type name, falling back to the raw value."""
    try:
        return PositionType(value).name
    except ValueError:
        return str(value)


def _optional_real(record: Record, key: str) -> float | None:
    """Numeric field value, or None when the log omits it."""
    try:
        return record.real(key)
    except (KeyError, TypeError):
        return None


def _optional_int(record: Record, key: str) -> int | None:
    """Integer field value, or None when the log omits it."""
    try:
        return record.integer(key)
    except (KeyError, TypeError):
        return None


def _std(values: Sequence[float]) -> float:
    """Population standard deviation, zero for fewer than two samples."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _mean_ecef(
    positions: Sequence[tuple[float, float, float]],
) -> tuple[float, float, float]:
    """Arithmetic mean of ECEF positions in metres."""
    count = len(positions)
    return (
        sum(point[0] for point in positions) / count,
        sum(point[1] for point in positions) / count,
        sum(point[2] for point in positions) / count,
    )


def _enu_residuals(
    positions: Sequence[tuple[float, float, float]],
    latitude: float,
    longitude: float,
) -> tuple[tuple[float, float, float], ...]:
    """Local east, north, up residuals of ECEF positions about their mean."""
    mean = _mean_ecef(positions)
    return tuple(
        enu_from_ecef(
            point[0] - mean[0],
            point[1] - mean[1],
            point[2] - mean[2],
            latitude,
            longitude,
        )
        for point in positions
    )


def ppp_epochs(records: Sequence[Record]) -> tuple[PppEpoch, ...]:
    """Parse PPPNAV fixes in receiver-epoch order."""
    epochs = [
        PppEpoch(
            record_epoch(record),
            record.real("lat"),
            record.real("lon"),
            record.real("hgt") + record.real("undulation"),
            record.integer("pos_type"),
            record.integer("sol_status"),
            _optional_real(record, "lat_std"),
            _optional_real(record, "lon_std"),
            _optional_real(record, "hgt_std"),
            record.integer("count_svs"),
            _optional_int(record, "count_solnsvs"),
            _optional_real(record, "diff_age"),
        )
        for record in records
    ]
    return tuple(sorted(epochs, key=lambda item: item.epoch))


def convergence(
    epochs: Sequence[PppEpoch],
    *,
    target_horizontal: float,
    target_vertical: float,
) -> Convergence:
    """Summarise PPP convergence from receiver sigmas and fix classes."""
    if not math.isfinite(target_horizontal) or not math.isfinite(target_vertical):
        raise ValueError("convergence targets must be finite")
    if target_horizontal <= 0 or target_vertical <= 0:
        raise ValueError("convergence targets must be positive")
    items = tuple(epochs)
    ppp = tuple(item for item in items if item.is_ppp)
    fixed = tuple(
        item
        for item in items
        if item.is_ppp
        and item.position_type
        in (PositionType.PPP, PositionType.PPP_AR, PositionType.PPP_RTK)
    )
    first = items[0].horizontal_sigma if items else None
    last = items[-1].horizontal_sigma if items else None
    improvement = (
        first / last if first is not None and last is not None and last > 0 else None
    )
    vertical = items[-1].height_sigma if items else None
    converged = (
        bool(fixed)
        and items[-1] in fixed
        and last is not None
        and vertical is not None
        and last <= target_horizontal
        and vertical <= target_vertical
    )
    classes = tuple(
        sorted(Counter(position_label(item.position_type) for item in items).items())
    )
    return Convergence(
        len(items),
        len(ppp),
        len(fixed),
        first,
        last,
        improvement,
        converged,
        classes,
    )


def mean_fix(epochs: Sequence[PppEpoch], *, ppp_only: bool = True) -> MeanFix:
    """Average PPP fixes into one ultra-precise position."""
    items = tuple(
        item
        for item in epochs
        if item.solution_status == 0 and (item.is_ppp or not ppp_only)
    )
    if not items:
        raise ValueError("no PPP fixes to average")
    positions = [
        ecef_from_geodetic(item.latitude, item.longitude, item.height) for item in items
    ]
    mean = _mean_ecef(positions)
    latitude, longitude, height = geodetic_from_ecef(*mean)
    residuals = _enu_residuals(positions, latitude, longitude)
    east = [item[0] for item in residuals]
    north = [item[1] for item in residuals]
    up = [item[2] for item in residuals]
    horizontal_scatter = math.sqrt(
        sum(value * value for value in east + north) / len(residuals)
    )
    vertical_scatter = math.sqrt(sum(value * value for value in up) / len(up))
    return MeanFix(
        latitude,
        longitude,
        height,
        mean,
        horizontal_scatter,
        vertical_scatter,
        items[-1].horizontal_sigma,
        items[-1].height_sigma,
        len(items),
        sum(item.is_ppp for item in items),
        "PPPNAV",
    )


def xyz_fallback(records: Sequence[Record]) -> MeanFix:
    """Average BESTXYZ ECEF fixes when no PPP fix is available."""
    positions = []
    for record in records:
        if record.get("p_sol_status") not in (0, "SOL_COMPUTED"):
            continue
        if record.get("pos_type") in (None, 0, "NONE"):
            continue
        for keys in (("x", "y", "z"), ("p_x", "p_y", "p_z")):
            try:
                point = (
                    record.real(keys[0]),
                    record.real(keys[1]),
                    record.real(keys[2]),
                )
                if all(math.isfinite(value) for value in point):
                    positions.append(point)
                break
            except (KeyError, TypeError):
                continue
    if not positions:
        raise ValueError("no BESTXYZ positions for a fallback fix")
    mean = _mean_ecef(positions)
    latitude, longitude, height = geodetic_from_ecef(*mean)
    residuals = _enu_residuals(positions, latitude, longitude)
    horizontal = math.sqrt(
        sum(item[0] ** 2 + item[1] ** 2 for item in residuals) / len(residuals)
    )
    vertical = math.sqrt(sum(item[2] ** 2 for item in residuals) / len(residuals))
    return MeanFix(
        latitude,
        longitude,
        height,
        mean,
        horizontal,
        vertical,
        None,
        None,
        len(positions),
        0,
        "BESTXYZ",
    )


def precision_statistics(epochs: Sequence[PppEpoch]) -> PrecisionStatistics:
    """Repeatability and receiver uncertainty of fixes about their mean.

    The P95 radius is a Rayleigh screening estimate derived from the observed
    horizontal scatter, not a calibrated confidence interval.
    """
    items = tuple(item for item in epochs if item.solution_status == 0)
    if not items:
        raise ValueError("no epochs for precision statistics")
    positions = [
        ecef_from_geodetic(item.latitude, item.longitude, item.height) for item in items
    ]
    mean = _mean_ecef(positions)
    latitude, longitude, _height = geodetic_from_ecef(*mean)
    residuals = _enu_residuals(positions, latitude, longitude)
    east = [item[0] for item in residuals]
    north = [item[1] for item in residuals]
    up = [item[2] for item in residuals]
    horizontal_scatter = math.sqrt(
        sum(value * value for value in east + north) / len(residuals)
    )
    vertical_scatter = math.sqrt(sum(value * value for value in up) / len(up))
    horizontal_sigmas = [
        item.horizontal_sigma for item in items if item.horizontal_sigma is not None
    ]
    vertical_sigmas = [
        item.height_sigma
        for item in items
        if item.height_sigma is not None and math.isfinite(item.height_sigma)
    ]
    first = items[0].horizontal_sigma
    last = items[-1].horizontal_sigma
    return PrecisionStatistics(
        len(items),
        max(item.epoch for item in items) - min(item.epoch for item in items),
        _std(east),
        _std(north),
        _std(up),
        horizontal_scatter,
        vertical_scatter,
        sum(horizontal_sigmas) / len(horizontal_sigmas) if horizontal_sigmas else None,
        min(horizontal_sigmas) if horizontal_sigmas else None,
        max(horizontal_sigmas) if horizontal_sigmas else None,
        sum(vertical_sigmas) / len(vertical_sigmas) if vertical_sigmas else None,
        _RAYLEIGH_P95_OVER_SCATTER * horizontal_scatter,
        first / last if first is not None and last is not None and last > 0 else None,
    )


def divergence_tally(
    per_signal: Sequence[tuple[str, int, int, int, float | None]],
) -> DivergenceTally:
    """Tally per-signal divergence summaries into one audit."""
    signals = len(per_signal)
    samples = sum(item[1] for item in per_signal)
    resets = sum(item[2] for item in per_signal)
    exceeds = sum(item[3] for item in per_signal)
    worst: float | None = None
    worst_signal: str | None = None
    for name, _samples, _resets, _exceeds, peak in per_signal:
        if peak is not None and (worst is None or peak > worst):
            worst, worst_signal = peak, name
    return DivergenceTally(signals, samples, resets, exceeds, worst, worst_signal)


def _detail(label: str, value: str) -> str:
    """One dot-leader report line with an aligned value column."""
    return f"  {label:.<26} {value}"


def _metres(value: float | None, digits: int = 3) -> str:
    """Metre reading with an explicit marker when the receiver omits it."""
    return f"{value:.{digits}f} m" if value is not None else "unknown"


def format_position(fix: MeanFix) -> tuple[str, ...]:
    """Aligned position lines for console reports."""
    return (
        _detail("source", fix.source),
        _detail("lat", f"{fix.latitude:.9f} deg"),
        _detail("lon", f"{fix.longitude:.9f} deg"),
        _detail("height", f"{fix.height:.3f} m ellipsoidal"),
        _detail("ECEF X", f"{fix.ecef[0]:.4f} m"),
        _detail("ECEF Y", f"{fix.ecef[1]:.4f} m"),
        _detail("ECEF Z", f"{fix.ecef[2]:.4f} m"),
    )


def format_precision(stats: PrecisionStatistics) -> tuple[str, ...]:
    """Aligned precision-statistic lines for console reports."""
    gain = f"{stats.improvement:.1f}x" if stats.improvement is not None else "n/a"
    return (
        _detail("epochs", f"{stats.epochs} ({stats.span_seconds:.1f} s span)"),
        _detail(
            "scatter H / V",
            f"{stats.horizontal_scatter:.3f} m / {stats.vertical_scatter:.3f} m",
        ),
        _detail(
            "std E / N / U",
            f"{stats.east_std:.3f} / {stats.north_std:.3f} / {stats.up_std:.3f} m",
        ),
        _detail("receiver sigma H mean", _metres(stats.mean_horizontal_sigma)),
        _detail(
            "receiver sigma H min/max",
            f"{_metres(stats.min_horizontal_sigma)} / "
            f"{_metres(stats.max_horizontal_sigma)}",
        ),
        _detail("receiver sigma V mean", _metres(stats.mean_vertical_sigma)),
        _detail("P95 radius (screening)", f"{stats.radius_p95:.3f} m"),
        _detail("improvement first/last", gain),
    )
