"""Application-defined checks of reported position quality."""

from dataclasses import dataclass
from math import isfinite

from um982py.quality import EpochSolution, FixClass


@dataclass(frozen=True, slots=True)
class PositionLimits:
    """Limits selected by the application, in seconds and metres.

    Each configured limit requires a finite, non-negative measurement. If a
    limit is omitted, its measurement is left unchecked.
    """

    max_epoch_age_s: float | None = None
    max_solution_age_s: float | None = None
    max_correction_age_s: float | None = None
    max_horizontal_std_m: float | None = None
    max_vertical_std_m: float | None = None
    allowed_fix_classes: frozenset[FixClass] | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_epoch_age_s",
            "max_solution_age_s",
            "max_correction_age_s",
            "max_horizontal_std_m",
            "max_vertical_std_m",
        ):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.allowed_fix_classes is not None and not self.allowed_fix_classes:
            raise ValueError("allowed_fix_classes must not be empty")


@dataclass(frozen=True, slots=True)
class PositionAssessment:
    solution: EpochSolution
    epoch_age_s: float | None
    horizontal_std_m: float | None
    vertical_std_m: float | None
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.reasons


def assess_position(
    solution: EpochSolution,
    limits: PositionLimits,
    *,
    epoch_age_s: float | None = None,
    horizontal_std_m: float | None = None,
    vertical_std_m: float | None = None,
) -> PositionAssessment:
    """Check a solution against the application's limits.

    Supply the epoch age in a compatible time scale. The standard deviations
    are receiver estimates and do not establish measured accuracy, navigation
    integrity, or safety certification.
    """
    reasons: list[str] = []
    try:
        available = solution.is_available
        fix_class = solution.fix_class
    except ValueError:
        available = False
        fix_class = None
        reasons.append("unknown_position_type")
    if not available:
        reasons.append("solution_unavailable")
    if (
        limits.allowed_fix_classes is not None
        and fix_class not in limits.allowed_fix_classes
    ):
        reasons.append("fix_class_not_allowed")
    checks = (
        ("epoch_age", epoch_age_s, limits.max_epoch_age_s),
        ("solution_age", solution.solution_age, limits.max_solution_age_s),
        ("correction_age", solution.differential_age, limits.max_correction_age_s),
        ("horizontal_std", horizontal_std_m, limits.max_horizontal_std_m),
        ("vertical_std", vertical_std_m, limits.max_vertical_std_m),
    )
    for name, value, maximum in checks:
        if maximum is None:
            continue
        if value is None or not isfinite(value) or value < 0:
            reasons.append(f"{name}_unknown")
        elif value > maximum:
            reasons.append(f"{name}_exceeded")
    return PositionAssessment(
        solution, epoch_age_s, horizontal_std_m, vertical_std_m, tuple(reasons)
    )
