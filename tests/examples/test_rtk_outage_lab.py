"""Checks RTK outage metrics against a labelled solver-state timeline."""

from pathlib import Path

import pytest
from examples.rtk_outage_lab import (
    Outage,
    PositionEpoch,
    analyse_outages,
    summarize_outages,
)
from examples.rtk_outage_lab.__main__ import main


def epochs() -> list[PositionEpoch]:
    """Known link interruption with transient and sustained fix returns."""
    return [
        PositionEpoch(
            float(i),
            (3.0 if i == 4 else 0.0, 4.0 if i == 4 else 0.0, 0),
            True,
            i not in (3, 4, 6),
            float(i),
        )
        for i in range(12)
    ]


def test_loss_recovery_and_truth_error_match_labelled_times() -> None:
    result = analyse_outages(
        epochs(), [Outage(2, 5)], truth=(0, 0, 0), sustained_seconds=3
    )[0]
    assert result.fixed_before is True
    assert result.first_nonfixed_after_start_s == 1
    assert result.recovery_after_end_s == 2
    assert not result.recovery_censored
    assert result.maximum_truth_error_m == 5
    assert result.maximum_position_step_m == 5


def test_incomplete_recovery_is_reported_as_censored() -> None:
    result = analyse_outages(epochs()[:9], [Outage(2, 5)], sustained_seconds=3)[0]
    assert result.recovery_censored
    assert result.recovery_after_end_s is None
    assert result.maximum_truth_error_m is None


def test_observation_gap_cannot_confirm_a_sustained_fix() -> None:
    data = [item for item in epochs() if item.epoch not in (8, 9, 10)]
    assert analyse_outages(data, [Outage(2, 5)], sustained_seconds=3)[
        0
    ].recovery_censored


def test_outage_outside_capture_cannot_be_scored() -> None:
    with pytest.raises(ValueError, match="cover"):
        analyse_outages(epochs(), [Outage(-1, 5)])


def test_campaign_summary_keeps_censoring_separate_from_recovery_times() -> None:
    recovered = analyse_outages(
        epochs(), [Outage(2, 5)], truth=(0, 0, 0), sustained_seconds=3
    )[0]
    censored = analyse_outages(epochs()[:9], [Outage(2, 5)], sustained_seconds=3)[0]
    summary = summarize_outages([recovered, censored])
    assert (summary.outages, summary.recovered, summary.recovery_censored) == (2, 1, 1)
    assert summary.median_observed_recovery_s == 2
    assert summary.p90_observed_recovery_s == 2
    assert summary.maximum_truth_error_m == 5


def test_cli_writes_plot_ready_timeline_without_absolute_position(
    tmp_path: Path,
) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures/specialist"
    timeline = tmp_path / "timeline.csv"
    assert (
        main(
            [
                "--replay",
                str(fixtures / "labelled-outage.bin"),
                "--outages",
                str(fixtures / "outages.csv"),
                "--timeline-csv",
                str(timeline),
                "--json",
                str(tmp_path / "report.json"),
            ]
        )
        == 0
    )
    rows = timeline.read_text().splitlines()
    assert rows[0] == "gps_epoch,computed,fixed,correction_age_s,truth_error_m"
    assert len(rows) > 2
    assert rows[1].endswith(",")
