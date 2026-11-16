from dataclasses import replace
from pathlib import Path

import pytest

from um982py.assessment import PositionLimits
from um982py.commands import Log
from um982py.convergence import ConvergenceMonitor
from um982py.messages import AsciiHeader, AsciiMessage
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.messages.navigation import BestNavigation
from um982py.ppp import PppSolution
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii
from um982py.quality import FixClass

LIMITS = PositionLimits(
    max_epoch_age_s=2,
    max_correction_age_s=5,
    max_horizontal_rms_m=0.1,
    max_vertical_std_m=0.1,
    allowed_fix_classes=frozenset({FixClass.PPP}),
)
BASE = BestNavigation.from_record(
    Log.BESTNAV.decode(
        parse_ascii(
            (Path(__file__).parent / "fixtures/bodies/BESTNAVA.bin").read_bytes()
        )
    )
)


def position(epoch: float, **changes: object) -> BestNavigation:
    message = BASE.message
    assert isinstance(message, AsciiMessage)
    assert isinstance(message.header, AsciiHeader)
    message = replace(
        message, header=replace(message.header, week=0, milliseconds=int(epoch * 1000))
    )
    result = replace(
        BASE,
        message=message,
        epoch_gps_seconds=epoch,
        position_type=PositionType.PPP,
        latitude_std_m=0.02,
        longitude_std_m=0.03,
        height_std_m=0.05,
        correction_age_s=1,
    )
    return replace(result, **changes)


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> ConvergenceMonitor:
    monkeypatch.setattr("um982py.convergence.monotonic", lambda: 0.0)
    return ConvergenceMonitor(
        LIMITS, min_epochs=3, hold_seconds=2, max_gap_seconds=2, timeout=10
    )


def test_convergence_requires_distinct_epochs_and_a_sustained_window(
    monitor: ConvergenceMonitor,
) -> None:
    first = monitor.observe(position(100), now_gps_seconds=100, now=0)
    assert first.epochs == 1 and not first.converged
    duplicate = monitor.observe(position(100), now_gps_seconds=100.5, now=0.5)
    assert duplicate.epochs == 1 and duplicate.span_s == 0
    assert not monitor.observe(position(101), now_gps_seconds=101, now=1).converged
    result = monitor.observe(position(102), now_gps_seconds=102, now=2)
    assert result.converged and result.epochs == 3 and result.span_s == 2
    assert monitor.status(now=2.5).converged
    duplicate = monitor.observe(position(102), now_gps_seconds=103, now=3)
    assert duplicate.converged and duplicate.epochs == 3 and duplicate.span_s == 2
    stale = monitor.status(now=4.1)
    assert not stale.converged and stale.epochs == 0
    assert {"epoch_age_exceeded", "gap_exceeded"} <= set(stale.reasons)


def test_a_burst_of_buffered_epochs_cannot_satisfy_host_hold_time(
    monitor: ConvergenceMonitor,
) -> None:
    for epoch in (100, 101, 102):
        result = monitor.observe(position(epoch), now_gps_seconds=epoch, now=0)
    assert result.epochs == 3 and result.span_s == 0
    assert result.reasons == ("hold_time_not_reached",)
    assert monitor.status(now=1).span_s == 0


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"latitude_std_m": 1}, "horizontal_rms_exceeded"),
        ({"height_std_m": None}, "vertical_std_unknown"),
        ({"correction_age_s": None}, "correction_age_unknown"),
        ({"correction_age_s": 6}, "correction_age_exceeded"),
        ({"position_type": PositionType.PPP_CONVERGING}, "fix_class_not_allowed"),
        ({"solution_status": SolutionStatus.INSUFFICIENT_OBS}, "solution_unavailable"),
    ],
)
def test_bad_quality_resets_consecutive_measurements(
    monitor: ConvergenceMonitor, changes: dict[str, object], reason: str
) -> None:
    monitor.observe(position(100), now_gps_seconds=100, now=0)
    rejected = monitor.observe(position(101, **changes), now_gps_seconds=101, now=1)
    assert reason in rejected.reasons and rejected.epochs == 0
    for elapsed in (2, 3, 4):
        result = monitor.observe(
            position(100 + elapsed), now_gps_seconds=100 + elapsed, now=elapsed
        )
        assert result.converged == (elapsed == 4)


def test_duplicate_quality_improvement_does_not_count_as_a_new_measurement(
    monitor: ConvergenceMonitor,
) -> None:
    monitor.observe(position(100, height_std_m=1), now_gps_seconds=100, now=0)
    result = monitor.observe(position(100), now_gps_seconds=100.5, now=0.5)
    assert result.epochs == 0 and not result.converged


def test_reordered_epochs_reset_without_lowering_the_epoch_watermark(
    monitor: ConvergenceMonitor,
) -> None:
    monitor.observe(position(100), now_gps_seconds=100, now=0)
    monitor.observe(position(101), now_gps_seconds=101, now=1)
    rejected = monitor.observe(position(100), now_gps_seconds=102, now=2)
    assert "epoch_not_increasing" in rejected.reasons and rejected.epochs == 0
    repeated = monitor.observe(position(101), now_gps_seconds=102, now=2)
    assert repeated.epochs == 0
    new = monitor.observe(position(102), now_gps_seconds=103, now=3)
    assert new.epochs == 1


@pytest.mark.parametrize(("epoch", "elapsed"), [(105, 1), (101, 5)])
def test_receiver_or_host_gaps_restart_the_window(
    monitor: ConvergenceMonitor, epoch: float, elapsed: float
) -> None:
    monitor.observe(position(100), now_gps_seconds=100, now=0)
    result = monitor.observe(position(epoch), now_gps_seconds=epoch, now=elapsed)
    assert result.epochs == 1 and result.span_s == 0


@pytest.mark.parametrize("epoch", [90, 200])
def test_stale_or_future_epochs_do_not_poison_later_valid_measurements(
    monitor: ConvergenceMonitor, epoch: float
) -> None:
    assert not monitor.observe(position(epoch), now_gps_seconds=100, now=0).converged
    assert monitor.observe(position(101), now_gps_seconds=101, now=1).epochs == 1


def test_unknown_time_quality_never_establishes_convergence(
    monitor: ConvergenceMonitor,
) -> None:
    for elapsed in (0, 1, 2):
        fix = position(100 + elapsed)
        assert isinstance(fix.message, AsciiMessage)
        assert isinstance(fix.message.header, AsciiHeader)
        fix = replace(
            fix,
            message=replace(
                fix.message, header=replace(fix.message.header, time_status="UNKNOWN")
            ),
        )
        result = monitor.observe(fix, now_gps_seconds=100 + elapsed, now=elapsed)
        assert result.epochs == 0 and "epoch_age_unknown" in result.reasons


def test_unverified_binary_ppp_time_is_rejected(monitor: ConvergenceMonitor) -> None:
    raw = (Path(__file__).parent / "fixtures/captures-extra/PPPNAVB.bin").read_bytes()
    fix = PppSolution.from_record(Log.PPPNAV.decode(StreamDecoder().feed(raw)[0]))
    assert fix.epoch_gps_seconds is not None
    result = monitor.observe(fix, now_gps_seconds=fix.epoch_gps_seconds, now=0)
    assert not result.converged and "epoch_age_unknown" in result.reasons


def test_correction_age_continues_to_advance_during_silence(
    monitor: ConvergenceMonitor,
) -> None:
    for elapsed in (0, 1, 2):
        result = monitor.observe(
            position(100 + elapsed, correction_age_s=4.5),
            now_gps_seconds=100 + elapsed,
            now=elapsed,
        )
    # The preceding samples expired their correction limits between updates.
    assert result.epochs == 1
    stale = monitor.status(now=2.6)
    assert stale.reasons == ("correction_age_exceeded",)
    assert not stale.converged


def test_deadline_expires_without_input_and_late_updates_cannot_succeed(
    monitor: ConvergenceMonitor,
) -> None:
    expired = monitor.status(now=10)
    assert expired.timed_out and not expired.converged and expired.epochs == 0
    assert "timeout" in expired.reasons
    assert monitor.observe(position(111), now_gps_seconds=111, now=11).timed_out


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), -1])
def test_invalid_host_times_are_rejected(
    monitor: ConvergenceMonitor, now: float
) -> None:
    with pytest.raises(ValueError):
        monitor.status(now=now)


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), -1])
def test_invalid_current_gps_times_are_rejected(
    monitor: ConvergenceMonitor, now: float
) -> None:
    with pytest.raises(ValueError):
        monitor.observe(position(100), now_gps_seconds=now, now=0)


@pytest.mark.parametrize(
    "options",
    [
        {"min_epochs": True},
        {"min_epochs": 1},
        {"hold_seconds": -1},
        {"hold_seconds": float("nan")},
        {"hold_seconds": 600},
        {"max_gap_seconds": 0},
        {"max_gap_seconds": float("inf")},
        {"timeout": True},
        {"timeout": 0},
    ],
)
def test_invalid_window_settings_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ConvergenceMonitor(LIMITS, **options)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "limits",
    [
        PositionLimits(),
        PositionLimits(max_epoch_age_s=2),
        PositionLimits(max_vertical_std_m=1),
    ],
)
def test_freshness_and_precision_limits_are_required(limits: PositionLimits) -> None:
    with pytest.raises(ValueError):
        ConvergenceMonitor(limits)
