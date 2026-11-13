from dataclasses import replace
from math import nan

import pytest

from um982py.assessment import PositionLimits, assess_position
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.quality import EpochSolution, FixClass


def solution() -> EpochSolution:
    return EpochSolution(
        100, PositionType.NARROW_INT, SolutionStatus.SOL_COMPUTED, 2, 1, 12
    )


def test_application_limits_report_missing_and_stale_values() -> None:
    limits = PositionLimits(
        max_epoch_age_s=2,
        max_solution_age_s=2,
        max_correction_age_s=5,
        max_horizontal_rms_m=0.1,
        allowed_fix_classes=frozenset({FixClass.FIXED}),
    )
    result = assess_position(solution(), limits, epoch_age_s=3, horizontal_rms_m=None)
    assert result.reasons == ("epoch_age_exceeded", "horizontal_rms_unknown")
    assert not result.accepted
    assert assess_position(
        solution(), limits, epoch_age_s=1, horizontal_rms_m=0.05
    ).accepted


def test_unknown_position_and_invalid_measurements_fail_closed() -> None:
    result = assess_position(
        replace(solution(), position_type=999, differential_age=nan),
        PositionLimits(max_correction_age_s=1),
    )
    assert result.reasons == (
        "unknown_position_type",
        "solution_unavailable",
        "correction_age_unknown",
    )
    with pytest.raises(ValueError):
        PositionLimits(max_epoch_age_s=nan)
