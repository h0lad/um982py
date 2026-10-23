"""Tests the precise static fix example against hand-computed statistics."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from examples.precise_fix import (
    FixSample,
    axis_statistics,
    clip_outliers,
    effective_sample_size,
    estimate,
    fix_sample,
    marker_position,
    position_rank,
    reference_error,
)

from um982py.capture import decode_records, read_frames
from um982py.experimental import FirmwareLog
from um982py.geodesy import ecef_from_geodetic, geodetic_from_ecef

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "captures" / "BESTXYZB.bin"
CENTRE = (3_782_563.8151, 899_476.2810, 5_039_205.3876)
FIXED_TYPE = 50
SINGLE_TYPE = 16
SMALL_SIGMA = 0.005


def sample(
    epoch: float,
    offsets: tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    pos_type: int = FIXED_TYPE,
    sigma: float = SMALL_SIGMA,
    satellites: int = 30,
    status: int = 0,
    undulation: float | None = None,
) -> FixSample:
    """One synthetic ECEF epoch around a fixed centre."""
    return FixSample(
        epoch,
        CENTRE[0] + offsets[0],
        CENTRE[1] + offsets[1],
        CENTRE[2] + offsets[2],
        pos_type,
        status,
        satellites,
        sigma,
        undulation,
    )


def test_position_rank_orders_the_documented_fix_classes() -> None:
    assert position_rank(0) == 0
    assert position_rank(SINGLE_TYPE) == 1
    assert position_rank(17) == 2
    assert position_rank(18) == 2
    assert position_rank(34) == 3
    assert position_rank(FIXED_TYPE) == 4
    assert position_rank(56) == 4
    assert position_rank(69) == 3
    assert position_rank(999) == 0


def test_axis_statistics_match_hand_computed_three_sample_values() -> None:
    axis = axis_statistics([1.0, 2.0, 3.0])
    assert axis.mean == pytest.approx(2.0)
    assert axis.std == pytest.approx(1.0)
    assert axis.standard_error == pytest.approx(1.0 / math.sqrt(3.0))
    assert axis.sigma95 == pytest.approx(1.96 / math.sqrt(3.0))
    assert math.isnan(axis_statistics([4.0]).std)


def test_axis_statistics_reject_empty_and_nonfinite_series() -> None:
    with pytest.raises(ValueError, match="at least one"):
        axis_statistics([])
    with pytest.raises(ValueError, match="finite"):
        axis_statistics([1.0, math.nan])


def test_serially_correlated_epochs_reduce_effective_sample_size() -> None:
    smooth = [math.sin(index / 8.0) for index in range(60)]
    alternating = [float(index % 2) for index in range(60)]
    assert effective_sample_size(smooth) < 10
    assert effective_sample_size(alternating) == 60
    with pytest.raises(ValueError, match="finite"):
        effective_sample_size([1.0, math.nan])


def test_convergence_uses_serially_adjusted_scatter() -> None:
    samples = [
        sample(float(index), (0.02 * math.sin(index / 8.0), 0.0, 0.0))
        for index in range(60)
    ]
    result = estimate(samples, minimum_samples=30, target_horizontal_sigma=0.01)
    assert result.effective_samples_enu[0] < result.accepted
    assert result.correlation_adjusted_horizontal_sigma > result.horizontal_sigma


def test_single_point_epochs_still_produce_a_fix() -> None:
    samples = [
        sample(float(index), (0.5 * math.sin(index), 0.0, 0.0), pos_type=SINGLE_TYPE)
        for index in range(30)
    ]
    result = estimate(samples)
    assert (result.samples, result.accepted, result.rejected) == (30, 30, 0)
    assert result.classes == (("single", 30),)
    assert not result.converged


def test_a_single_epoch_still_produces_a_fix() -> None:
    result = estimate([sample(0.0, pos_type=SINGLE_TYPE)])
    assert result.accepted == 1
    assert math.isnan(result.east.std)
    assert result.trace == ()


def test_mixed_classes_are_counted_next_to_the_average() -> None:
    samples = [
        sample(0.0, pos_type=FIXED_TYPE),
        sample(1.0, pos_type=34),
        sample(2.0, pos_type=SINGLE_TYPE),
        sample(3.0, pos_type=SINGLE_TYPE),
    ]
    result = estimate(samples)
    assert result.classes == (("single", 2), ("float", 1), ("fixed", 1))


def test_uncomputed_solutions_are_reported_without_blocking_the_fix() -> None:
    samples = [sample(float(index)) for index in range(10)]
    samples.append(sample(10.0, status=1))
    result = estimate(samples)
    assert (result.accepted, result.rejected) == (10, 1)
    assert result.rejections[0].reason == "solution_not_computed"


def test_one_gross_outlier_is_clipped_and_does_not_move_the_mean() -> None:
    epochs = [
        sample(float(index), (0.002 * math.sin(index), 0.0, 0.0)) for index in range(40)
    ]
    outliers = [sample(40.0, (10.0, 0.0, 0.0))]
    result = estimate([*epochs, *outliers])
    assert result.accepted == 40
    assert result.rejected == 1
    assert result.rejections[0].reason == "outlier"
    assert result.ecef[0] == pytest.approx(CENTRE[0], abs=1e-3)


def test_clipping_retains_at_least_half_of_a_noisy_occupation() -> None:
    inliers = [
        sample(float(index), (0.001 * math.sin(index), 0.0, 0.0)) for index in range(5)
    ]
    outliers = [
        sample(float(10 + index), (100.0 + index, 0.0, 0.0)) for index in range(3)
    ]
    kept, rejected = clip_outliers([*inliers, *outliers])
    assert len(kept) >= len(inliers + outliers) // 2
    assert rejected
    result = estimate([*inliers, *outliers])
    assert result.accepted >= 1
    assert result.ecef[0] == pytest.approx(CENTRE[0], abs=1.0)


def test_clipping_leaves_small_and_identical_sets_untouched() -> None:
    three = [sample(float(index), (float(index), 0.0, 0.0)) for index in range(3)]
    kept, rejected = clip_outliers(three)
    assert kept == tuple(three)
    assert not rejected
    identical = [sample(float(index)) for index in range(10)]
    kept, rejected = clip_outliers(identical)
    assert len(kept) == 10
    assert not rejected


def test_msl_height_uses_the_geoid_separation_of_the_same_epochs() -> None:
    samples = [sample(float(index), undulation=-48.0) for index in range(30)]
    result = estimate(samples)
    assert result.undulation == pytest.approx(-48.0)
    assert result.height_msl == pytest.approx(result.height + 48.0)
    without = estimate([sample(float(index)) for index in range(30)])
    assert without.height_msl is None and without.undulation is None


def test_convergence_is_reported_but_never_blocks() -> None:
    samples = [sample(float(index)) for index in range(10)]
    reached = estimate(samples, minimum_samples=5)
    assert reached.converged
    pending = estimate(samples, minimum_samples=20)
    assert not pending.converged
    assert pending.accepted == 10
    noisy = [
        sample(float(index), (0.01 * math.sin(index), 0.0, 0.0)) for index in range(10)
    ]
    assert not estimate(
        noisy,
        minimum_samples=5,
        target_horizontal_sigma=0.0001,
        target_vertical_sigma=0.02,
    ).converged


def test_convergence_trace_shrinks_as_epochs_accumulate() -> None:
    samples = [
        sample(float(index), (0.01 if index % 2 else -0.01, 0.0, 0.0))
        for index in range(30)
    ]
    trace = estimate(samples).trace
    assert len(trace) == 29
    assert trace[-1] < trace[0]
    assert trace[-1] < 0.01


def test_marker_position_moves_down_the_local_up_axis() -> None:
    equator = ecef_from_geodetic(0.0, 0.0, 100.0)
    marker = marker_position(equator, 1.5)
    assert marker[0] == pytest.approx(equator[0] - 1.5, abs=1e-9)
    assert marker[1] == pytest.approx(equator[1], abs=1e-9)
    assert marker[2] == pytest.approx(equator[2], abs=1e-9)
    assert marker_position(equator, 0.0) == pytest.approx(equator)


def test_reference_error_is_east_for_an_eastward_offset() -> None:
    latitude, longitude, height = 52.5, 13.4, 74.0
    position = ecef_from_geodetic(latitude, longitude, height)
    assert reference_error(position, position) == pytest.approx((0.0, 0.0, 0.0))
    shifted = ecef_from_geodetic(latitude, longitude + 1e-6, height)
    east, north, up = reference_error(shifted, position)
    assert east > 0
    assert abs(north) < 1e-6 and abs(up) < 1e-6


def test_invalid_estimate_options_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        estimate([sample(0.0)], sigma_k=-1.0)
    with pytest.raises(ValueError, match="positive"):
        estimate([sample(0.0)], minimum_samples=0)
    with pytest.raises(ValueError, match="target sigmas"):
        estimate([sample(0.0)], target_horizontal_sigma=0.0)


def test_fixture_bestxyz_decodes_into_a_sample() -> None:
    records = decode_records(read_frames(FIXTURE), FirmwareLog.BESTXYZ)
    assert records
    decoded = fix_sample(records[0])
    assert decoded.position_type == SINGLE_TYPE
    assert decoded.sigma_3d > 0
    assert math.isfinite(decoded.epoch)
    assert geodetic_from_ecef(*decoded.ecef)[2] > -500.0


def test_failed_solutions_never_become_a_successful_average() -> None:
    with pytest.raises(ValueError, match="computed position"):
        estimate([sample(0.0, status=1)])


def test_single_epoch_cannot_claim_convergence() -> None:
    result = estimate([sample(0.0)], minimum_samples=1)
    assert not result.converged
    assert math.isnan(result.horizontal_sigma)


def test_outlier_on_an_otherwise_identical_axis_is_rejected() -> None:
    epochs = [sample(float(i)) for i in range(10)]
    result = estimate([*epochs, sample(10.0, (10.0, 0.0, 0.0))])
    assert result.accepted == 10
    assert result.rejected == 1


def test_horizontal_bound_contains_isotropic_gaussian_95_percent_circle() -> None:
    result = estimate(
        [
            sample(float(i), (0.01 * math.sin(i), 0.02 * math.cos(i), 0.0))
            for i in range(30)
        ]
    )
    assert result.horizontal_95 == pytest.approx(
        math.sqrt(-2 * math.log(0.05)) * result.horizontal_sigma
    )


def test_reference_residual_uses_the_reference_tangent_plane() -> None:
    reference = ecef_from_geodetic(0.0, 0.0, 0.0)
    position = ecef_from_geodetic(0.0, 90.0, 0.0)
    assert reference_error(position, reference) == pytest.approx(
        (position[1], 0.0, -reference[0]), abs=1e-8
    )


def test_unconverged_occupation_has_explicit_status() -> None:
    from examples.precise_fix.__main__ import _payload

    result = estimate([sample(0.0)])
    assert (
        _payload(result, antenna_height=0, reference=None)["status"] == "not_converged"
    )
