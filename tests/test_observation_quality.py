import pytest

from tests.examples._new_api import observation, record
from um982py.observation_quality import audit_observations


def test_gaps_and_reported_lock_resets() -> None:
    records = [record(0, [observation(lock=100)]), record(2, [observation(lock=1)])]
    quality = audit_observations(records, expected_interval=1)
    assert len(quality.gaps) == 1
    assert len(quality.lock_resets) == 1
    assert quality.lock_resets[0].previous_lock_seconds == 100
    assert quality.lock_resets[0].lock_seconds == 1
    assert audit_observations(records).gaps == ()


def test_invalid_flags_duplicates_and_epoch_validation() -> None:
    first = record(0, [observation(valid=False), observation(valid=False)])
    quality = audit_observations([first])
    assert (
        quality.missing_code_flags,
        quality.missing_phase_flags,
        quality.duplicate_signals,
    ) == (2, 2, 1)
    assert quality.lock_resets == ()
    with pytest.raises(ValueError, match="increase"):
        audit_observations([first, first])
    with pytest.raises(ValueError, match="interval"):
        audit_observations([first], expected_interval=0)
