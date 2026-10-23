"""Tests the scintillation monitor example against ground truth."""

from __future__ import annotations

import math

import pytest
from examples.scintillation_monitor import (
    ScintillationEpoch,
    ScintillationSample,
    attribute_lock_loss,
    linear_power,
    roti_proxy,
    s4_index,
    sliding_s4,
    summarise,
    unambiguous_samples,
)

MODULATION = 0.6
PERIOD_SAMPLES = 360
MODULATION_TOLERANCE = 0.02
TWO_TONE_TOLERANCE = 1e-3


def db_hz(powers: list[float]) -> list[float]:
    """C/N0 in dB-Hz of a linear power series."""
    return [10.0 * math.log10(power) for power in powers]


def modulated_powers(count: int, depth: float) -> list[float]:
    """One full period of P * (1 + depth * sin(wt))."""
    return [
        1.0 + depth * math.sin(2.0 * math.pi * index / count) for index in range(count)
    ]


def two_tone_powers(count: int, amplitude_a: float, amplitude_b: float) -> list[float]:
    """One full beat period of A1^2 + A2^2 + 2 A1 A2 cos(wt)."""
    steady = amplitude_a * amplitude_a + amplitude_b * amplitude_b
    beat = 2.0 * amplitude_a * amplitude_b
    return [
        steady + beat * math.cos(2.0 * math.pi * index / count)
        for index in range(count)
    ]


def test_linear_power_is_ten_to_the_tenth_db_hz() -> None:
    assert linear_power(40.0) == pytest.approx(10_000.0, rel=1e-15)
    assert linear_power(0.0) == pytest.approx(1.0, abs=0.0)
    for cn0 in (-3.0, 0.5, 27.0, 51.5):
        assert linear_power(cn0) == pytest.approx(10 ** (cn0 / 10), rel=1e-15)


def test_constant_signal_has_zero_s4() -> None:
    assert s4_index([3.7] * 32) == pytest.approx(0.0, abs=1e-15)
    powers = [linear_power(cn0) for cn0 in db_hz([2.5] * 16)]
    assert sliding_s4(powers, 8) == pytest.approx([0.0] * 9, abs=1e-15)


def test_modulated_signal_has_s4_of_the_depth_over_root_two() -> None:
    powers = [linear_power(cn0) for cn0 in db_hz(modulated_powers(360, MODULATION))]
    assert s4_index(powers) == pytest.approx(
        MODULATION / math.sqrt(2), rel=MODULATION_TOLERANCE
    )


def test_equal_two_tone_fading_has_s4_of_one_over_root_two() -> None:
    powers = two_tone_powers(PERIOD_SAMPLES, 1.0, 1.0)
    assert s4_index(powers) == pytest.approx(1.0 / math.sqrt(2), rel=TWO_TONE_TOLERANCE)


def test_unequal_two_tone_fading_matches_the_closed_form() -> None:
    amplitude_a, amplitude_b = 1.0, 0.5
    expected = (
        math.sqrt(2) * amplitude_a * amplitude_b / (amplitude_a**2 + amplitude_b**2)
    )
    powers = two_tone_powers(PERIOD_SAMPLES, amplitude_a, amplitude_b)
    assert s4_index(powers) == pytest.approx(expected, rel=TWO_TONE_TOLERANCE)


def test_sliding_window_reports_one_index_per_window_position() -> None:
    powers = modulated_powers(PERIOD_SAMPLES, MODULATION) * 2
    series = sliding_s4(powers, PERIOD_SAMPLES)
    assert len(series) == PERIOD_SAMPLES + 1
    assert series == pytest.approx(
        [MODULATION / math.sqrt(2)] * len(series), rel=MODULATION_TOLERANCE
    )


def test_roti_proxy_is_the_sigma_of_the_s4_increments() -> None:
    expected = math.sqrt(0.02)
    assert roti_proxy([0.0, 0.1, 0.4]) == pytest.approx(expected, rel=1e-12)
    assert roti_proxy([0.0, 0.1, 0.4], 2.0) == pytest.approx(expected / 2.0, rel=1e-12)
    assert math.isnan(roti_proxy([0.5, 0.5]))


def test_summarise_keeps_prn_and_channel_apart() -> None:
    powers = modulated_powers(PERIOD_SAMPLES, MODULATION)
    values = db_hz(powers)
    samples = [ScintillationSample("7", 0, value) for value in values]
    samples += [ScintillationSample("7", 1, value) for value in values]
    samples.append(ScintillationSample("9", 0, 20.0))
    summaries = summarise(samples, window=PERIOD_SAMPLES)
    assert [(summary.prn, summary.frequency_channel) for summary in summaries] == [
        ("7", 0),
        ("7", 1),
        ("9", 0),
    ]
    assert summaries[0].s4 == pytest.approx(
        MODULATION / math.sqrt(2), rel=MODULATION_TOLERANCE
    )
    assert summaries[2].sample_count == 1
    assert math.isnan(summaries[2].s4)


def test_a_signal_reported_twice_in_one_frame_is_dropped() -> None:
    frames = [
        [
            ScintillationSample("7", 0, 20.0),
            ScintillationSample("7", 0, 31.0),
            ScintillationSample("8", 0, 25.0),
        ],
        [ScintillationSample("7", 0, 21.0), ScintillationSample("8", 0, 24.0)],
    ]
    remaining = unambiguous_samples(frames)
    assert [(sample.prn, sample.frequency_channel) for sample in remaining] == [
        ("8", 0),
        ("8", 0),
    ]


def test_window_below_two_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least two"):
        sliding_s4([1.0, 2.0, 3.0], 1)
    with pytest.raises(ValueError, match="at least two"):
        s4_index([1.0])
    with pytest.raises(ValueError, match="positive"):
        s4_index([0.0, 0.0])
    with pytest.raises(ValueError, match="interval"):
        roti_proxy([0.1, 0.2], 0.0)


def test_scintillation_without_written_slots_is_a_receiver_side_lock_loss() -> None:
    result = attribute_lock_loss(
        [
            ScintillationEpoch(0.0, 0.2, 12),
            ScintillationEpoch(2.0, 0.7, 9),
            ScintillationEpoch(1.0, 0.8, 0),
        ]
    )
    assert [(entry.epoch, entry.attribution) for entry in result] == [
        (1.0, "no_tracking_while_scintillating"),
        (2.0, "tracking_under_scintillation"),
    ]
    assert [entry.written_slots for entry in result] == [0, 9]


def test_scintillation_threshold_and_slot_minimum_are_explicit() -> None:
    epochs = [ScintillationEpoch(0.0, 0.6, 3)]
    assert not attribute_lock_loss(epochs, s4_threshold=0.61)
    assert attribute_lock_loss(epochs)[0].attribution == "tracking_under_scintillation"
    assert (
        attribute_lock_loss(epochs, minimum_slots=4)[0].attribution
        == "no_tracking_while_scintillating"
    )


def test_invalid_scintillation_epochs_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        attribute_lock_loss([ScintillationEpoch(0.0, 0.9, 0)], s4_threshold=-1.0)
    with pytest.raises(ValueError, match="non-negative"):
        attribute_lock_loss([ScintillationEpoch(0.0, 0.9, 0)], minimum_slots=-1)
    invalid = (
        ScintillationEpoch(0.0, 0.9, -1),
        ScintillationEpoch(0.0, math.nan, 1),
    )
    for epoch in invalid:
        with pytest.raises(ValueError):
            attribute_lock_loss([epoch])


@pytest.mark.parametrize("powers", [[-1.0, 3.0], [math.nan, 1.0], [math.inf, 1.0]])
def test_nonphysical_power_windows_are_rejected(powers: list[float]) -> None:
    with pytest.raises(ValueError, match="finite"):
        s4_index(powers)


def test_large_constant_power_has_no_cancellation_noise() -> None:
    assert s4_index([1e12] * 60) == 0.0
