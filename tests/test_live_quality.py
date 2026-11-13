from dataclasses import replace
from datetime import UTC, datetime

import pytest

from um982py.live import PositionUpdate
from um982py.live_quality import LiveLimits, PositionMonitor
from um982py.messages.navigation import Fix


def update(
    time: float, *, quality: int = 4, longitude: float = 8, connection: int = 1
) -> PositionUpdate:
    fix = Fix("120000", 50, longitude, quality, 10, 1, 100, 45, 1, "base")
    return PositionUpdate(fix, datetime.now(UTC), time, None, connection)


def test_monitor_reports_gap_jump_and_stale_corrections() -> None:
    monitor = PositionMonitor(
        LiveLimits(max_gap_s=2, max_correction_age_s=3, max_displacement_rate_m_s=5)
    )
    assert monitor.observe(update(10)).reasons == ("displacement_rate_unknown",)
    current = update(14, longitude=8.01)
    current = replace(current, fix=replace(current.fix, correction_age_s=5))
    report = monitor.observe(current)
    assert report.gap_s == 4 and report.displacement_rate_m_s is not None
    assert report.reasons == (
        "correction_age_exceeded",
        "gap_exceeded",
        "displacement_rate_exceeded",
    )
    assert monitor.age(now=15) == 1


def test_monitor_does_not_compare_positions_across_reconnect() -> None:
    monitor = PositionMonitor(LiveLimits(max_displacement_rate_m_s=5))
    monitor.observe(update(10))
    report = monitor.observe(update(11, longitude=9, connection=2))
    assert report.displacement_rate_m_s is None
    assert report.reasons == ("displacement_rate_unknown",)
    same_time = monitor.observe(update(11))
    assert same_time.reasons == ("displacement_rate_unknown",)
    with pytest.raises(ValueError, match="nondecreasing"):
        monitor.observe(update(10))


def test_monitor_does_not_treat_missing_corrections_as_fresh() -> None:
    monitor = PositionMonitor(
        LiveLimits(max_correction_age_s=5, allowed_quality=frozenset({4}))
    )
    current = update(1, quality=0)
    current = replace(current, fix=replace(current.fix, correction_age_s=None))
    report = monitor.observe(current)
    assert report.reasons == (
        "solution_unavailable",
        "fix_quality_not_allowed",
        "correction_age_unknown",
    )


def test_monitor_reports_ongoing_outages_and_correction_age() -> None:
    monitor = PositionMonitor(LiveLimits(max_gap_s=3, max_correction_age_s=4))
    missing = monitor.status(now=9)
    assert not missing.accepted and missing.reasons == ("position_unavailable",)
    report = monitor.observe(update(10))
    assert monitor.status(now=12).accepted
    assert monitor.status(now=12).assessment is report
    stale = monitor.status(now=14)
    assert stale.age_s == 4
    assert stale.reasons == ("position_stale", "correction_age_exceeded")
    assert not stale.accepted
    with pytest.raises(ValueError, match="monotonic"):
        monitor.status(now=9)
    monitor.observe(update(15))
    assert monitor.status(now=15).reasons == ("gap_exceeded",)
    monitor.observe(update(16))
    assert monitor.status(now=16).accepted
