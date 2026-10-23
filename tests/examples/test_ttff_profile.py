"""Tests the time-to-first-fix profile against ground truth."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from examples.rtk_quality import FixClass
from examples.ttff_profile import (
    FixEpoch,
    StartKind,
    TtffMeasurement,
    compare_starts,
    fix_transitions,
    measure,
    repeatability,
)
from examples.ttff_profile.__main__ import main

from um982py.commands.types import ResetTarget
from um982py.messages.enums import PositionType, SolutionStatus

COLD_MEAN = 45.0
WARM_MEAN = 12.0


def epoch(seconds: float, position_type: PositionType) -> FixEpoch:
    """One epoch whose solution status follows its position type."""
    computed = position_type is not PositionType.NONE
    return FixEpoch(
        seconds=seconds,
        solution_status=(
            SolutionStatus.SOL_COMPUTED if computed else SolutionStatus.INSUFFICIENT_OBS
        ),
        position_type=position_type,
        satellites=9 if computed else 0,
    )


def timeline(
    *,
    single: float | None = None,
    floating: float | None = None,
    fixed: float | None = None,
    epochs: int = 121,
    cadence: float = 1.0,
) -> tuple[FixEpoch, ...]:
    """Epochs at a fixed cadence, changing class at the stated times."""
    epochs_out = []
    for index in range(epochs):
        seconds = index * cadence
        if fixed is not None and seconds >= fixed:
            position_type = PositionType.NARROW_INT
        elif floating is not None and seconds >= floating:
            position_type = PositionType.NARROW_FLOAT
        elif single is not None and seconds >= single:
            position_type = PositionType.SINGLE
        else:
            position_type = PositionType.NONE
        epochs_out.append(epoch(seconds, position_type))
    return tuple(epochs_out)


def runs(*values: float, start: StartKind = StartKind.COLD) -> list[TtffMeasurement]:
    """One measurement per injected time to first fix."""
    return [
        measure(timeline(single=value), start=start, reset_seconds=0.0)
        for value in values
    ]


def test_the_documented_cold_start_clears_every_target() -> None:
    assert StartKind.COLD.reset_targets == (ResetTarget.ALL,)
    assert StartKind.WARM.reset_targets == ()
    assert StartKind.COLD.reset_command().text == "RESET ALL"
    assert StartKind.WARM.reset_command().text == "RESET"


def test_measured_ttff_equals_the_injected_transition_time() -> None:
    run = measure(timeline(single=45.0), start=StartKind.COLD, reset_seconds=0.0)
    assert run.ttff == pytest.approx(45.0, abs=1e-9)
    assert run.start is StartKind.COLD
    assert run.target is FixClass.SINGLE


def test_measured_ttff_keeps_the_sub_second_resolution() -> None:
    run = measure(
        timeline(single=12.5, cadence=0.5), start=StartKind.WARM, reset_seconds=0.0
    )
    assert run.ttff == pytest.approx(12.5, abs=1e-9)


def test_the_target_class_decides_which_transition_is_the_fix() -> None:
    epochs = timeline(single=45.0, floating=60.0)
    assert measure(
        epochs, start=StartKind.COLD, reset_seconds=0.0
    ).ttff == pytest.approx(45.0, abs=1e-9)
    assert measure(
        epochs, start=StartKind.COLD, reset_seconds=0.0, target=FixClass.FLOAT
    ).ttff == pytest.approx(60.0, abs=1e-9)
    assert (
        measure(
            epochs, start=StartKind.COLD, reset_seconds=0.0, target=FixClass.FIXED
        ).ttff
        is None
    )


def test_epochs_before_the_reset_are_ignored() -> None:
    epochs = (
        *timeline(single=5.0, epochs=11),
        *(epoch(seconds, PositionType.NONE) for seconds in range(11, 30)),
        *(epoch(seconds, PositionType.SINGLE) for seconds in range(30, 43)),
    )
    run = measure(epochs, start=StartKind.COLD, reset_seconds=30.0)
    assert run.fix_seconds == pytest.approx(30.0, abs=1e-9)
    assert run.ttff == pytest.approx(0.0, abs=1e-9)


def test_an_epoch_without_a_computed_solution_is_not_a_fix() -> None:
    epochs = (
        *timeline(epochs=45),
        FixEpoch(
            seconds=45.0,
            solution_status=SolutionStatus.INSUFFICIENT_OBS,
            position_type=PositionType.SINGLE,
            satellites=8,
        ),
        *timeline(single=47.0, epochs=121)[45:],
    )
    run = measure(epochs, start=StartKind.COLD, reset_seconds=0.0)
    assert run.ttff == pytest.approx(47.0, abs=1e-9)


def test_fix_transitions_report_each_class_once_in_order() -> None:
    transitions = fix_transitions(timeline(single=45.0, floating=60.0, fixed=90.0))
    assert [(fix_class, seconds) for fix_class, seconds in transitions] == [
        (FixClass.SINGLE, 45.0),
        (FixClass.FLOAT, 60.0),
        (FixClass.FIXED, 90.0),
    ]


def test_fix_transitions_skip_a_class_the_timeline_never_reaches() -> None:
    transitions = fix_transitions(timeline(single=45.0, fixed=90.0))
    assert [fix_class for fix_class, _ in transitions] == [
        FixClass.SINGLE,
        FixClass.FIXED,
    ]


def test_repeatability_of_three_runs_is_the_closed_form_statistics() -> None:
    statistics = repeatability(runs(44.0, 45.0, 46.0))
    assert statistics.runs == 3
    assert statistics.mean_seconds == pytest.approx(45.0, abs=1e-12)
    assert statistics.stddev_seconds == pytest.approx(1.0, abs=1e-12)
    assert statistics.minimum_seconds == pytest.approx(44.0, abs=1e-12)
    assert statistics.maximum_seconds == pytest.approx(46.0, abs=1e-12)
    assert statistics.spread_seconds == pytest.approx(2.0, abs=1e-12)


def test_repeatability_rejects_a_set_that_mixes_start_kinds() -> None:
    mixed = [
        *runs(45.0, start=StartKind.COLD),
        *runs(12.0, start=StartKind.WARM),
    ]
    with pytest.raises(ValueError):
        repeatability(mixed)


def test_repeatability_rejects_a_run_without_a_fix() -> None:
    without_fix = measure(
        timeline(), start=StartKind.COLD, reset_seconds=0.0, target=FixClass.FIXED
    )
    with pytest.raises(ValueError):
        repeatability([without_fix])


def test_the_documented_warm_start_is_faster_than_a_cold_start() -> None:
    comparison = compare_starts(
        repeatability(runs(44.0, 45.0, 46.0)),
        repeatability(runs(11.0, 12.0, 13.0, start=StartKind.WARM)),
    )
    assert comparison.cold_seconds == pytest.approx(COLD_MEAN, abs=1e-12)
    assert comparison.warm_seconds == pytest.approx(WARM_MEAN, abs=1e-12)
    assert comparison.difference_seconds == pytest.approx(
        COLD_MEAN - WARM_MEAN, abs=1e-12
    )
    assert comparison.documented_order


def test_a_slow_warm_start_violates_the_documented_order() -> None:
    comparison = compare_starts(
        repeatability(runs(20.0)),
        repeatability(runs(30.0, start=StartKind.WARM)),
    )
    assert not comparison.documented_order


def test_compare_starts_rejects_a_warm_statistic_in_the_cold_slot() -> None:
    warm = repeatability(runs(12.0, start=StartKind.WARM))
    with pytest.raises(ValueError):
        compare_starts(warm, warm)


def test_main_reports_the_documented_cold_warm_order(tmp_path: Path) -> None:
    destination = tmp_path / "profile.json"
    assert main(["--json", str(destination)]) == 0
    payload = json.loads(destination.read_text())
    assert [statistic["start"] for statistic in payload["statistics"]] == [
        StartKind.COLD,
        StartKind.WARM,
    ]
    assert payload["comparison"]["documented_order"]
    assert payload["comparison"]["difference_seconds"] == pytest.approx(
        COLD_MEAN - WARM_MEAN, abs=1e-12
    )
    assert math.isfinite(payload["statistics"][0]["mean_seconds"])


def test_ppp_does_not_satisfy_an_rtk_target() -> None:
    epochs = (epoch(1.0, PositionType.PPP_CONVERGING), epoch(2.0, PositionType.PPP))
    assert measure(epochs, start=StartKind.WARM, reset_seconds=0).ttff == 1.0
    assert (
        measure(epochs, start=StartKind.WARM, reset_seconds=0, target=FixClass.PPP).ttff
        == 2.0
    )
    assert (
        measure(
            epochs, start=StartKind.WARM, reset_seconds=0, target=FixClass.FLOAT
        ).ttff
        is None
    )
    assert fix_transitions(epochs) == (
        (FixClass.PPP_CONVERGING, 1.0),
        (FixClass.PPP, 2.0),
    )
