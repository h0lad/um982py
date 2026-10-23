"""Tests the signal quality report example."""

from __future__ import annotations

import pytest
from examples.signal_quality_report import (
    LOCK_BOUNDARIES,
    ChannelTracking,
    LockBucket,
    SignalObservation,
    as_dict,
    lock_bucket,
    summarise,
)

from um982py.messages.enums import SatelliteSystem

SORTED_SAMPLE = (10.0, 20.0, 30.0, 40.0, 50.0)
RESERVED_ONLY_BITS = (0, 1, 11, 13, 14, 15, 19, 20, 27, 31)


def observation(
    cn0: float, lock_time: float = 0.0, channel: int = 0
) -> SignalObservation:
    return SignalObservation(
        prn=1,
        frequency_channel=channel,
        cn0=cn0,
        lock_time=lock_time,
        tracking=ChannelTracking(0),
    )


def test_percentiles_match_hand_computed_values_for_a_sorted_list() -> None:
    summary = summarise([observation(cn0) for cn0 in SORTED_SAMPLE])
    assert summary.cn0_p10 == pytest.approx(14.0, abs=1e-12)
    assert summary.cn0_p50 == pytest.approx(30.0, abs=1e-12)
    assert summary.cn0_p90 == pytest.approx(46.0, abs=1e-12)


def test_median_of_an_even_length_list_is_the_mean_of_the_middle_pair() -> None:
    summary = summarise([observation(cn0) for cn0 in (10.0, 20.0, 30.0, 40.0)])
    assert summary.cn0_p50 == pytest.approx(25.0, abs=1e-12)


def test_tracking_status_bits_decode_the_documented_fields() -> None:
    raw = 0x04000000 | (17 << 21) | (1 << 16) | (1 << 12) | (1 << 10) | (3 << 5)
    tracking = ChannelTracking(raw)
    assert tracking.channel_number == 3
    assert tracking.carrier_phase_valid is True
    assert tracking.pseudorange_valid is True
    assert tracking.satellite_system is SatelliteSystem.GLONASS
    assert tracking.signal_type == 17
    assert tracking.is_l2c is True


def test_reserved_tracking_bits_are_not_interpreted() -> None:
    raw = sum(1 << bit for bit in RESERVED_ONLY_BITS)
    tracking = ChannelTracking(raw)
    assert tracking.raw != 0
    assert tracking.carrier_phase_valid is False
    assert tracking.pseudorange_valid is False
    assert tracking.satellite_system is SatelliteSystem.GPS
    assert tracking.signal_type == 0
    assert tracking.is_l2c is False


def test_reserved_satellite_system_code_has_no_constellation() -> None:
    assert ChannelTracking(7 << 16).satellite_system is None


def test_lock_time_buckets_cover_the_documented_boundaries() -> None:
    boundaries = [bound for bound, _ in LOCK_BOUNDARIES]
    assert boundaries == [1.0, 10.0, 60.0, 600.0]
    assert lock_bucket(0.0) is LockBucket.UNDER_ONE_SECOND
    assert lock_bucket(0.999) is LockBucket.UNDER_ONE_SECOND
    assert lock_bucket(1.0) is LockBucket.UNDER_TEN_SECONDS
    assert lock_bucket(10.0) is LockBucket.UNDER_ONE_MINUTE
    assert lock_bucket(60.0) is LockBucket.UNDER_TEN_MINUTES
    assert lock_bucket(600.0) is LockBucket.OVER_TEN_MINUTES


def test_machine_readable_summary_keys() -> None:
    payload = as_dict(summarise([observation(30.0, lock_time=5.0, channel=6)]))
    assert payload["observation_count"] == 1
    assert payload["cn0_db_hz"] == {"p10": 30.0, "p50": 30.0, "p90": 30.0}
    assert payload["lock_seconds"] == {
        str(LockBucket.UNDER_ONE_SECOND): 0,
        str(LockBucket.UNDER_TEN_SECONDS): 1,
        str(LockBucket.UNDER_ONE_MINUTE): 0,
        str(LockBucket.UNDER_TEN_MINUTES): 0,
        str(LockBucket.OVER_TEN_MINUTES): 0,
    }
    assert payload["frequency_channel"] == {"6": 1}
    assert payload["satellite_system"] == {SatelliteSystem.GPS.name: 1}


def test_empty_observation_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        summarise([])
