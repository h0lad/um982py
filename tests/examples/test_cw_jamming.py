"""Tests the continuous-wave jamming example."""

from __future__ import annotations

import pytest
from examples.cw_jamming import (
    CW_FLAGS,
    CW_RATIO_MAXIMUM,
    SEVERITY_ORDER,
    Band,
    CwFlag,
    CwState,
    Evidence,
    InterferenceClass,
    JamSample,
    alerts,
    fingerprint,
    flag_of,
    severity_rank,
    state_of,
    timeline,
    worst_flag,
)

CLEAN_EPOCHS = 10
ESCAPED_EPOCHS = 25
SERIES_EPOCHS = 60
RATIO_PER_EPOCH = 4


def sample(epoch: int, band: Band, ratio: int, flag: CwFlag) -> JamSample:
    return JamSample(epoch=epoch, band=band, state=CwState(ratio=ratio, flag=flag))


def escalation() -> list[JamSample]:
    return [
        sample(0, Band.L1, 0, CwFlag.NO_JAM),
        sample(1, Band.L1, 12, CwFlag.NO_JAM),
        sample(2, Band.L1, 140, CwFlag.JAM),
        sample(3, Band.L1, 140, CwFlag.JAM),
        sample(4, Band.L1, CW_RATIO_MAXIMUM, CwFlag.STRONG_JAM),
        sample(5, Band.L5, 60, CwFlag.JAM),
    ]


def long_series() -> list[JamSample]:
    samples: list[JamSample] = []
    for epoch in range(SERIES_EPOCHS):
        flag = CwFlag.NO_JAM
        if epoch >= ESCAPED_EPOCHS:
            flag = CwFlag.STRONG_JAM
        elif epoch >= CLEAN_EPOCHS:
            flag = CwFlag.JAM
        samples.append(sample(epoch, Band.L1, RATIO_PER_EPOCH * epoch, flag))
        samples.append(sample(epoch, Band.L2, 0, CwFlag.NO_JAM))
        samples.append(sample(epoch, Band.L5, 3, CwFlag.NO_JAM))
    return samples


def test_every_documented_code_maps_to_its_class() -> None:
    assert flag_of(0) is CwFlag.NO_JAM
    assert flag_of(1) is CwFlag.JAM
    assert flag_of(2) is CwFlag.STRONG_JAM
    assert sorted(CW_FLAGS) == [0, 1, 2]


def test_unknown_flag_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown jamming flag 3"):
        flag_of(3)


def test_ratio_outside_the_documented_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        state_of(CW_RATIO_MAXIMUM + 1, 0)
    with pytest.raises(ValueError, match="outside"):
        state_of(-1, 0)


def test_non_integer_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="ratio"):
        state_of(1.5, 0)
    with pytest.raises(ValueError, match="flag"):
        state_of(3, "cw_jam")


def test_severity_rank_follows_the_manual_order() -> None:
    assert [severity_rank(flag) for flag in SEVERITY_ORDER] == [0, 1, 2]


def test_worst_flag_picks_the_most_severe_class() -> None:
    flags = (CwFlag.JAM, CwFlag.STRONG_JAM, CwFlag.NO_JAM)
    assert worst_flag(flags) is CwFlag.STRONG_JAM
    with pytest.raises(ValueError, match="at least one flag"):
        worst_flag(())


def test_timeline_aggregates_a_many_record_series() -> None:
    summary = timeline(
        [sample.state for sample in long_series() if sample.band is Band.L1]
    )
    assert summary.epochs == SERIES_EPOCHS
    assert summary.jammed_epochs == SERIES_EPOCHS - CLEAN_EPOCHS
    assert summary.worst_flag is CwFlag.STRONG_JAM
    assert summary.peak_ratio == RATIO_PER_EPOCH * (SERIES_EPOCHS - 1)
    assert summary.first_jam_epoch == CLEAN_EPOCHS


def test_clean_series_reports_no_jammed_epoch() -> None:
    summary = timeline(
        [sample.state for sample in long_series() if sample.band is Band.L2]
    )
    assert summary.jammed_epochs == 0
    assert summary.first_jam_epoch is None
    assert summary.worst_flag is CwFlag.NO_JAM
    assert summary.peak_ratio == 0


def test_empty_series_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        timeline(())


def test_escalation_produces_the_expected_alert_order() -> None:
    found = alerts(escalation())
    assert [(alert.epoch, alert.band, alert.current) for alert in found] == [
        (2, Band.L1, CwFlag.JAM),
        (4, Band.L1, CwFlag.STRONG_JAM),
        (5, Band.L5, CwFlag.JAM),
    ]
    assert [alert.previous for alert in found] == [
        CwFlag.NO_JAM,
        CwFlag.JAM,
        CwFlag.NO_JAM,
    ]
    assert [alert.ratio for alert in found] == [
        140,
        CW_RATIO_MAXIMUM,
        60,
    ]


def test_steady_class_raises_one_alert_per_change_only() -> None:
    found = alerts(long_series())
    assert [(alert.epoch, alert.band) for alert in found] == [
        (CLEAN_EPOCHS, Band.L1),
        (ESCAPED_EPOCHS, Band.L1),
    ]


def test_recovery_is_reported_as_a_class_change() -> None:
    samples = [
        sample(0, Band.L1, 200, CwFlag.STRONG_JAM),
        sample(1, Band.L1, 8, CwFlag.NO_JAM),
    ]
    found = alerts(samples)
    assert len(found) == 2
    assert found[0].current is CwFlag.STRONG_JAM
    assert found[0].previous is CwFlag.NO_JAM
    assert found[1].current is CwFlag.NO_JAM
    assert found[1].previous is CwFlag.STRONG_JAM


def test_only_a_reported_band_is_narrowband_not_wideband() -> None:
    quiet = CwState(0, CwFlag.NO_JAM)
    jammed = CwState(180, CwFlag.JAM)
    assert fingerprint(5, {Band.L1: jammed, Band.L2: quiet}).interference == (
        InterferenceClass.NARROWBAND
    )
    wide = fingerprint(5, {Band.L1: jammed, Band.L2: jammed, Band.L5: jammed})
    assert wide.interference == InterferenceClass.WIDEBAND
    assert wide.jammed_bands == (Band.L1, Band.L2, Band.L5)


def test_quiet_epoch_reports_no_source_and_no_strongest_band() -> None:
    quiet = fingerprint(6, {Band.L1: CwState(0, CwFlag.NO_JAM)})
    assert quiet.interference == InterferenceClass.QUIET
    assert quiet.strongest is None
    assert quiet.evidence == Evidence.CONSISTENT


def test_class_word_and_strength_contradictions_are_reported() -> None:
    strong = fingerprint(
        7,
        {
            Band.L1: CwState(CW_RATIO_MAXIMUM, CwFlag.NO_JAM),
            Band.L2: CwState(0, CwFlag.NO_JAM),
            Band.L5: CwState(0, CwFlag.NO_JAM),
        },
    )
    assert strong.evidence == Evidence.RATIO_WITHOUT_FLAG
    assert strong.interference == InterferenceClass.QUIET
    flagged = fingerprint(8, {Band.L1: CwState(0, CwFlag.JAM)})
    assert flagged.evidence == Evidence.FLAG_WITHOUT_RATIO
    assert flagged.strongest == Band.L1


def test_strongest_band_breaks_ratio_ties_in_documented_order() -> None:
    states = {
        Band.L5: CwState(120, CwFlag.JAM),
        Band.L2: CwState(120, CwFlag.JAM),
        Band.L1: CwState(12, CwFlag.JAM),
    }
    assert fingerprint(9, states).strongest == Band.L2


def test_fingerprint_rejects_missing_and_out_of_range_states() -> None:
    with pytest.raises(ValueError, match="at least one band"):
        fingerprint(1, {})
    with pytest.raises(ValueError, match="documented ratio"):
        fingerprint(1, {Band.L1: CwState(CW_RATIO_MAXIMUM + 1, CwFlag.JAM)})
