"""Tests the dual-antenna spoofing checks against ground truth."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from examples.spoof_dual_antenna import (
    SKY_FRAMES_PER_SNAPSHOT,
    SKY_TOLERANCE_DEGREES,
    Alarm,
    BearingCandidates,
    EcefBaseline,
    EnuBaseline,
    HeadingOffset,
    SkyEntry,
    SkyView,
    SpoofStatus,
    alarms,
    apply_heading_offset,
    bearing_candidates,
    circular_difference,
    compare_headings,
    compare_sky,
    compare_snapshots,
    resolve_bearing,
    sky_snapshots,
)

from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures"

ENU_EAST, ENU_NORTH, ENU_UP = 0.0011, 0.0051, 0.0038
ECEF_X, ECEF_Y, ECEF_Z = -0.0038, 0.0101, -0.0169


def records(name: str) -> tuple[Record, ...]:
    log = FirmwareLog(name.rstrip("AB"))
    decoded = []
    for message in StreamDecoder().feed((FIXTURES / f"{name}.bin").read_bytes()):
        for binary in (True, False):
            if log.request(binary=binary).matches(message):
                decoded.append(log.decode(message))
                break
    return tuple(decoded)


def first(name: str) -> Record:
    return records(name)[0]


def tight_baseline(east: float, north: float, up: float) -> EnuBaseline:
    return EnuBaseline(east, north, up, 1e-5, 1e-5, 1e-5)


def test_heading_sigma_uses_the_perpendicular_component() -> None:
    baseline = EnuBaseline(0.0, 1.0, 0.0, 0.01, 0.02, 0.0)
    assert baseline.heading_sigma == pytest.approx(math.degrees(0.01 / 1.0), rel=1e-12)


def test_heading_sigma_is_undefined_without_a_horizontal_baseline() -> None:
    with pytest.raises(ValueError, match="horizontal"):
        _ = EnuBaseline(0.0, 0.0, 1.0, 0.1, 0.1, 0.1).heading_sigma


def test_circular_difference_wraps_across_north() -> None:
    assert circular_difference(359.0, 1.0) == pytest.approx(-2.0, abs=1e-9)
    assert circular_difference(1.0, 359.0) == pytest.approx(2.0, abs=1e-9)


def test_injected_heading_inconsistency_is_flagged() -> None:
    baseline = tight_baseline(0.0, 1.0, 0.0)
    rotated = tight_baseline(1.0, 0.0, 0.0)
    agreement = compare_headings(baseline, rotated)
    assert agreement.difference == pytest.approx(-90.0, abs=1e-9)
    assert agreement.sigma == pytest.approx(
        math.degrees(math.hypot(1e-5, 1e-5)), rel=1e-9
    )
    assert agreement.consistent is False
    assert alarms(agreement, (), SpoofStatus("NARROW_INT", 0)) == (
        Alarm.BASELINE_HEADING,
    )


def test_mount_offset_is_removed_from_the_reported_heading() -> None:
    baseline = tight_baseline(0.0, 1.0, 0.0)
    shifted = apply_heading_offset(baseline, HeadingOffset(10.0, 0.0))
    assert circular_difference(shifted.heading, baseline.heading) == pytest.approx(
        -10.0, abs=1e-9
    )
    assert shifted.length == pytest.approx(baseline.length, rel=1e-12)


def test_captures_group_into_one_snapshot_per_request() -> None:
    snapshots = sky_snapshots((*records("SATVIS2A"), *records("SATVIS2B")))
    assert len(snapshots) == pytest.approx(2, abs=0)
    assert all(len(snapshot) == SKY_FRAMES_PER_SNAPSHOT for snapshot in snapshots)
    comparisons = compare_snapshots(snapshots[0], snapshots[1])
    assert len(comparisons) == pytest.approx(7, abs=0)
    assert all(comparison.consistent for comparison in comparisons)


def test_real_sky_views_agree_within_the_capture_tolerance() -> None:
    first_view, second_view = sky_snapshots(
        (*records("SATVIS2A"), *records("SATVIS2B"))
    )
    comparisons = compare_snapshots(first_view, second_view)
    assert all(comparison.consistent for comparison in comparisons)
    azimuth = max(
        abs(item.azimuth_difference)
        for comparison in comparisons
        for item in comparison.disagreements
    )
    elevation = max(
        abs(item.elevation_difference)
        for comparison in comparisons
        for item in comparison.disagreements
    )
    assert azimuth == pytest.approx(0.0933, abs=1e-4)
    assert elevation == pytest.approx(0.0582, abs=1e-4)
    assert azimuth < SKY_TOLERANCE_DEGREES


def test_satellite_count_difference_between_the_two_captures_is_reported() -> None:
    first_view = SkyView.from_record(records("SATVIS2A")[3])
    second_view = SkyView.from_record(records("SATVIS2B")[3])
    comparison = compare_sky(first_view, second_view)
    assert comparison.absent == (35,)
    assert len(comparison.shared) == pytest.approx(8, abs=0)


def test_injected_sky_inconsistency_is_flagged() -> None:
    baseline = SkyView.from_record(records("SATVIS2A")[0])
    shifted = SkyView(
        tuple(
            SkyEntry(satellite.prn, satellite.elevation + 1.0, satellite.azimuth)
            if satellite.prn == 16
            else satellite
            for satellite in baseline.satellites
        )
    )
    comparison = compare_sky(baseline, shifted)
    assert comparison.consistent is False
    assert alarms(
        compare_headings(tight_baseline(0.0, 1.0, 0.0), tight_baseline(0.0, 1.0, 0.0)),
        [comparison],
        SpoofStatus("NARROW_INT", 0),
    ) == (Alarm.SKY_VIEW,)


def test_real_spoof_info_reports_no_indicator() -> None:
    status = SpoofStatus.from_record(first("SPOOFINFOA"))
    assert status.position_type == "SINGLE"
    assert status.indicator == pytest.approx(0, abs=0)
    assert status.spoofed is False


def test_injected_spoof_indicator_is_flagged() -> None:
    status = SpoofStatus("SINGLE", 1)
    assert status.spoofed is True
    assert alarms(
        compare_headings(tight_baseline(0.0, 1.0, 0.0), tight_baseline(0.0, 1.0, 0.0)),
        (),
        status,
    ) == (Alarm.SPOOF_INDICATOR,)


def test_empty_sky_views_are_consistent() -> None:
    comparison = compare_sky(SkyView(()), SkyView(()))
    assert comparison.shared == ()
    assert comparison.absent == ()
    assert comparison.consistent is True


def test_broadside_phase_yields_two_mirror_bearings() -> None:
    candidates = bearing_candidates(
        0.0,
        baseline_heading=90.0,
        baseline_length_m=1.0,
        wavelength_m=0.19,
    )
    assert candidates.separation_degrees == pytest.approx(90.0)
    assert candidates.candidate_bearings == pytest.approx((180.0, 0.0))
    assert candidates.leverage == pytest.approx(1.0)
    assert candidates.distinct
    assert resolve_bearing(candidates, 10.0) == pytest.approx(0.0)
    assert resolve_bearing(candidates, 170.0) == pytest.approx(180.0)


def test_endfire_phase_collapses_both_bearings_onto_the_baseline() -> None:
    wavelength = 0.19
    candidates = bearing_candidates(
        1.0 / wavelength,
        baseline_heading=90.0,
        baseline_length_m=1.0,
        wavelength_m=wavelength,
    )
    assert candidates.separation_degrees == pytest.approx(0.0)
    assert candidates.candidate_bearings == pytest.approx((90.0, 90.0))
    assert candidates.leverage == pytest.approx(0.0)
    assert not candidates.distinct


def test_a_phase_beyond_the_baseline_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds the baseline"):
        bearing_candidates(
            1.0,
            baseline_heading=0.0,
            baseline_length_m=0.1,
            wavelength_m=0.19,
        )
    for invalid in (math.nan, math.inf):
        with pytest.raises(ValueError, match="finite"):
            bearing_candidates(
                invalid,
                baseline_heading=0.0,
                baseline_length_m=1.0,
                wavelength_m=0.19,
            )
    with pytest.raises(ValueError, match="positive"):
        bearing_candidates(
            0.0, baseline_heading=0.0, baseline_length_m=0.0, wavelength_m=0.19
        )


def test_bearing_resolution_needs_a_finite_reference() -> None:
    candidates = BearingCandidates(60.0, (100.0, 40.0), 0.866, True)
    with pytest.raises(ValueError, match="reference heading"):
        resolve_bearing(candidates, math.nan)


def test_negated_baselines_rotate_heading_and_mirror_pitch() -> None:
    baseline = EnuBaseline(1.0, 0.0, 0.5, 0.01, 0.02, 0.03)
    negated = baseline.negated()
    assert negated.length == pytest.approx(baseline.length)
    assert abs(circular_difference(negated.heading, baseline.heading)) == pytest.approx(
        180.0
    )
    assert negated.pitch == pytest.approx(-baseline.pitch)
    assert (negated.sigma_east, negated.sigma_north, negated.sigma_up) == (
        0.01,
        0.02,
        0.03,
    )
    ecef = EcefBaseline(1.0, 2.0, 3.0, 0.1, 0.2, 0.3).negated()
    assert (ecef.x, ecef.y, ecef.z) == (-1.0, -2.0, -3.0)
    assert (ecef.sigma_x, ecef.sigma_y, ecef.sigma_z) == (0.1, 0.2, 0.3)
