"""Tests the RTK quality example."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from examples.rtk_quality import (
    POSITION_CLASSES,
    EpochSolution,
    FixClass,
    classify,
    summarise,
    timeline,
)
from examples.rtk_quality.__main__ import _diagnostic_rows

from um982py.capture import decode_records, read_frames
from um982py.experimental import FirmwareLog
from um982py.messages.enums import PositionType, SolutionStatus


def test_fixed_ppp_remains_distinct_from_rtk_fix() -> None:
    for position_type in (PositionType.PPP_AR, PositionType.PPP_RTK):
        solution = epoch(0, position_type)
        assert solution.is_available
        assert solution.fix_class is FixClass.PPP
        assert not solution.fresh_fixed


def epoch(epoch: int, position_type: PositionType) -> EpochSolution:
    return EpochSolution(
        epoch=epoch,
        position_type=position_type,
        solution_status=SolutionStatus.SOL_COMPUTED,
        differential_age=0.5,
        solution_age=1.0,
        satellites_used=20,
    )


def counts(solutions: Sequence[EpochSolution]) -> dict[FixClass, int]:
    return dict(summarise(solutions).class_counts)


def test_every_documented_position_type_has_a_fix_class() -> None:
    uncovered = set(PositionType) - set(POSITION_CLASSES)
    assert uncovered == {PositionType.DOPPLER_VELOCITY, PositionType.INS}


def test_unclassifiable_position_types_are_rejected() -> None:
    with pytest.raises(ValueError, match="no fix class"):
        classify(PositionType.DOPPLER_VELOCITY)
    with pytest.raises(ValueError, match="unknown position type"):
        classify(200)


def test_summary_counts_availability_and_ages() -> None:
    solutions = [
        epoch(0, PositionType.NONE),
        epoch(1, PositionType.SINGLE),
        epoch(2, PositionType.NARROW_FLOAT),
        epoch(3, PositionType.NARROW_INT),
        epoch(4, PositionType.NARROW_INT),
    ]
    summary = summarise(solutions)
    assert summary.epochs == 5
    assert summary.availability == pytest.approx(0.8, abs=1e-12)
    assert summary.time_to_first_fix == 3
    assert summary.mean_differential_age == pytest.approx(0.5, abs=1e-12)
    assert summary.maximum_solution_age == pytest.approx(1.0, abs=1e-12)
    assert counts(solutions) == {
        FixClass.NONE: 1,
        FixClass.SINGLE: 1,
        FixClass.FLOAT: 1,
        FixClass.FIXED: 2,
        FixClass.PPP: 0,
        FixClass.PPP_CONVERGING: 0,
    }


def test_insufficient_observations_is_not_available() -> None:
    solution = EpochSolution(
        epoch=0,
        position_type=PositionType.NARROW_INT,
        solution_status=SolutionStatus.INSUFFICIENT_OBS,
        differential_age=0.0,
        solution_age=1.0,
        satellites_used=3,
    )
    assert solution.fix_class is FixClass.FIXED
    assert solution.is_available is False


def test_stale_fixed_epochs_are_excluded_from_time_to_first_fix() -> None:
    stale = EpochSolution(
        epoch=0,
        position_type=PositionType.NARROW_INT,
        solution_status=SolutionStatus.SOL_COMPUTED,
        differential_age=419.0,
        solution_age=91.0,
        satellites_used=20,
    )
    fresh = epoch(1, PositionType.NARROW_INT)
    summary = summarise((stale, fresh))
    assert stale.is_available
    assert not stale.fresh_fixed
    assert summary.fresh_fixed_epochs == 1
    assert summary.time_to_first_fix == 1


def test_empty_timeline_is_rejected() -> None:
    assert timeline([]) == ()
    with pytest.raises(ValueError, match="at least one solution epoch"):
        summarise([])


def test_ppp_solutions_keep_their_own_categories() -> None:
    solutions = [epoch(0, PositionType.PPP_CONVERGING), epoch(1, PositionType.PPP)]
    summary = summarise(solutions)
    assert [solution.fix_class for solution in solutions] == [
        FixClass.PPP_CONVERGING,
        FixClass.PPP,
    ]
    assert summary.class_counts[FixClass.FLOAT] == 0
    assert summary.class_counts[FixClass.PPP_CONVERGING] == 1
    assert summary.class_counts[FixClass.PPP] == 1
    assert summary.fresh_fixed_epochs == 0


def test_diagnostics_preserve_raw_flags_and_separate_timestamps() -> None:
    root = Path("tests/fixtures")
    files = {
        FirmwareLog.RTKDOP: root / "captures/RTKDOPA.bin",
        FirmwareLog.BESTSATS: root / "captures/BESTSATSA.bin",
        FirmwareLog.RTKSTATUS2: root / "captures-extra/RTKSTATUS2A.bin",
    }
    captured = {
        log.value: decode_records(read_frames(path), log) for log, path in files.items()
    }
    report = _diagnostic_rows(captured)
    sats = report["BESTSATS"]
    assert isinstance(sats, list) and len(sats) == 1
    assert sats[0]["satellites"][0]["flags"] == 3
    dop = report["RTKDOP"]
    assert isinstance(dop, list) and dop[0]["pdop"] == 9999
    assert "not matched" in str(report["limitation"])
