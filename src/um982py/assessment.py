"""Application-defined checks of reported position quality."""

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from um982py.messages.enums import FixClass, PositionType, enum_member
from um982py.messages.navigation import Fix
from um982py.quality import EpochSolution

if TYPE_CHECKING:
    from um982py.messages.navigation import Position


@dataclass(frozen=True, slots=True)
class PositionLimits:
    """Limits selected by the application, in seconds and metres.

    A measurement must be finite and non-negative to pass a configured limit.
    Omit a limit to skip that check.
    """

    max_epoch_age_s: float | None = None
    max_solution_age_s: float | None = None
    max_correction_age_s: float | None = None
    max_horizontal_rms_m: float | None = None
    max_vertical_std_m: float | None = None
    allowed_fix_classes: frozenset[FixClass] | None = None
    reject_predicted: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_epoch_age_s",
            "max_solution_age_s",
            "max_correction_age_s",
            "max_horizontal_rms_m",
            "max_vertical_std_m",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isfinite(value) or value < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.allowed_fix_classes is not None and not self.allowed_fix_classes:
            raise ValueError("allowed_fix_classes must not be empty")


@dataclass(frozen=True, slots=True)
class PositionAssessment:
    solution: "EpochSolution | Position"
    epoch_age_s: float | None
    horizontal_rms_m: float | None
    vertical_std_m: float | None
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.reasons


def limit_reason(name: str, value: float | None, maximum: float | None) -> str | None:
    """Return ``<name>_unknown`` or ``<name>_exceeded`` when a limit is not met.

    A measurement must be finite and non-negative to pass a configured limit.
    """
    if maximum is None:
        return None
    if value is None or not isfinite(value) or value < 0:
        return f"{name}_unknown"
    return f"{name}_exceeded" if value > maximum else None


def assess_position(
    solution: "EpochSolution | Position",
    limits: PositionLimits,
    *,
    epoch_age_s: float | None = None,
    horizontal_rms_m: float | None = None,
    vertical_std_m: float | None = None,
    now_gps_seconds: float | None = None,
) -> PositionAssessment:
    """Check a solution against the application's limits.

    Position objects supply their precision and correction age automatically.
    An explicit epoch age must use a compatible scale. Alternatively pass a
    verified current GPS epoch, in which case age is computed only for
    documented fine receiver time. Standard deviations are estimates, not
    accuracy bounds.
    """
    reasons: list[str] = []
    if now_gps_seconds is not None and (
        isinstance(now_gps_seconds, bool)
        or not isfinite(now_gps_seconds)
        or now_gps_seconds < 0
    ):
        raise ValueError("now_gps_seconds must be finite and non-negative")
    if epoch_age_s is not None and now_gps_seconds is not None:
        raise ValueError("supply epoch_age_s or now_gps_seconds, not both")
    fix_class = None
    solution_age: float | None
    correction_age: float | None
    if isinstance(solution, EpochSolution):
        try:
            available = solution.is_available
            fix_class = solution.fix_class
        except ValueError:
            available = False
            reasons.append("unknown_position_type")
        solution_age = solution.solution_age
        correction_age = solution.differential_age
    else:
        available = solution.valid
        native = getattr(solution, "position", solution)
        if isinstance(native, Fix):
            fix_class = native.fix_class
            if limits.reject_predicted:
                predicted = native.possibly_predicted
                if predicted is True:
                    reasons.append("position_possibly_predicted")
                elif predicted is None:
                    reasons.append("prediction_status_unknown")
        else:
            member = enum_member(PositionType, getattr(native, "position_type", None))
            fix_class = None if member is None else member.fix_class
        solution_age = getattr(native, "solution_age_s", None)
        correction_age = solution.correction_age_s
        precision = solution.precision
        if precision is not None:
            if horizontal_rms_m is None:
                horizontal_rms_m = precision.horizontal_rms_m
            if vertical_std_m is None:
                vertical_std_m = precision.up_std_m
        if now_gps_seconds is not None:
            stamp = solution.receiver_time
            if (
                stamp is not None
                and stamp.fine is True
                and not stamp.assumed_scale
                and stamp.gps_seconds is not None
            ):
                epoch_age_s = now_gps_seconds - stamp.gps_seconds
    if not available:
        reasons.append("solution_unavailable")
    if (
        limits.allowed_fix_classes is not None
        and fix_class not in limits.allowed_fix_classes
    ):
        reasons.append("fix_class_not_allowed")
    checks = (
        ("epoch_age", epoch_age_s, limits.max_epoch_age_s),
        ("solution_age", solution_age, limits.max_solution_age_s),
        ("correction_age", correction_age, limits.max_correction_age_s),
        ("horizontal_rms", horizontal_rms_m, limits.max_horizontal_rms_m),
        ("vertical_std", vertical_std_m, limits.max_vertical_std_m),
    )
    reasons.extend(
        reason
        for name, value, maximum in checks
        if (reason := limit_reason(name, value, maximum)) is not None
    )
    return PositionAssessment(
        solution, epoch_age_s, horizontal_rms_m, vertical_std_m, tuple(reasons)
    )
