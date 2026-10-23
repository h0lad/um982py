"""Analytic checks for the scientific experiment building blocks."""

import math

import pytest

from um982py.science_experiments import (
    C,
    noise_multipath_summary,
    orbit_position_effect,
    phase_detrended,
    slip_detection_matrix,
    slip_response,
    tec_phase_change,
    tec_spatial_summary,
    uncertainty_coverage,
)


def test_tec_change_with_ambiguity_offsets() -> None:
    high, low = 1575.42e6, 1227.60e6
    delay = 40.3e16 * (1 / low**2 - 1 / high**2)
    # The large independent phase ambiguities cancel from each continuous arc.
    assert tec_phase_change(
        300, -500, 300 + 2 * delay, -500, high, low
    ) == pytest.approx(2, abs=1e-11)
    with pytest.raises(ValueError):
        tec_phase_change(0, 0, 0, 0, low, high)
    assert tec_spatial_summary([1, 2, 3], [2, 4, 6])["correlation"] == pytest.approx(1)


def test_noise_and_repeat_track() -> None:
    result = noise_multipath_summary([-1, 1], [-2, 2], [1, 2, 3], [3, 2, 1])
    assert result["shared_variance_m2"] == 2
    assert result["variance_difference_m2"] == 6
    assert result["repeat_correlation"] == pytest.approx(-1)


def test_slip_closed_form_and_blind_case() -> None:
    freqs = (1575.42e6, 1227.6e6, 1176.45e6)
    response = slip_response(freqs, (1, 0, 0))
    assert response["gf12_m"] == pytest.approx(C / freqs[0])
    assert response["closure_m"] == pytest.approx(C / freqs[0])
    matrix = slip_detection_matrix(freqs, 1, 0.05, 0.05)
    assert len(matrix) == 26
    third = next(x for x in matrix if x["slips_cycles"] == (0, 0, 1))
    assert not third["gf_detected"] and third["closure_detected"]


def test_coverage_and_detrending() -> None:
    coverage = uncertainty_coverage([1, -3, 0], [1, 2, 1])
    assert coverage["covered"] == 2
    assert coverage["fraction"] == pytest.approx(2 / 3)
    result = phase_detrended([0, 1, 2], [100, 103, 104], 2)
    assert result["slope_m_per_s"] == pytest.approx(2)
    assert result["residual_rms_m"] == pytest.approx(math.sqrt(2) / 3)
    with pytest.raises(ValueError):
        phase_detrended([0, 1, 5], [0, 1, 2], 2)


def test_orbit_solution_translation_and_common_clock() -> None:
    q = 1 / math.sqrt(3)
    u = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-q, -q, -q)]
    result = orbit_position_effect(u, [(2.0, -3.0, 4.0)] * 4, [1e-9] * 4, [1] * 4)
    assert result["ecef_change_m"] == pytest.approx([2, -3, 4])
    assert result["receiver_clock_change_m"] == pytest.approx(C * 1e-9)
    with pytest.raises(ValueError):
        orbit_position_effect(
            [(1.0, 0.0, 0.0)] * 4, [(0.0, 0.0, 0.0)] * 4, [0.0] * 4, [1.0] * 4
        )
