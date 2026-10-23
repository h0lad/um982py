"""Tests the cycle-slip detection example against ground truth."""

from __future__ import annotations

from collections.abc import Sequence

from examples.cycle_slip_detection import (
    GEOMETRY_FREE_THRESHOLD_METRES,
    SLIP_THRESHOLD_CYCLES,
    DualFrequencyPhase,
    Observation,
    Slip,
    common_mode_events,
    detect_slips,
    geometry_free_slips,
    report,
)
from pytest import approx

from um982py.geodesy import wavelength

L1_HZ = 1575.42e6
L2_HZ = 1227.60e6
DOPPLER_HZ = 1500.0
DOPPLER_RATE = 0.05
STEP_CYCLES = 2.5
STEP_EPOCH = 60.0


def epoch_times(count: int = 121) -> list[float]:
    """Uniform one-second epochs."""
    return [float(index) for index in range(count)]


def phase_record(
    epochs: Sequence[float],
    *,
    step_cycles: float = 0.0,
    step_epoch: float = STEP_EPOCH,
    rate: float = DOPPLER_RATE,
    prn: int = 7,
) -> tuple[Observation, ...]:
    """Carrier phase integrated from a linear Doppler, with an optional step."""
    observations = []
    for epoch in epochs:
        doppler = DOPPLER_HZ + rate * epoch
        carrier_phase = 41.0 + DOPPLER_HZ * epoch + 0.5 * rate * epoch**2
        if epoch >= step_epoch:
            carrier_phase += step_cycles
        observations.append(
            Observation(
                prn=prn, epoch=epoch, carrier_phase=carrier_phase, doppler=doppler
            )
        )
    return tuple(observations)


def dual_frequency(
    epochs: Sequence[float], *, slip_cycles: float = 0.0, slip_epoch: float = 10.0
) -> tuple[DualFrequencyPhase, ...]:
    """Geometry-free samples of a satellite with an optional L1 cycle slip."""
    phases = []
    for epoch in epochs:
        geometry = 22_000_000.0 + 300.0 * epoch
        high = -(geometry + 7 * wavelength(L1_HZ)) / wavelength(L1_HZ)
        low = -(geometry + 11 * wavelength(L2_HZ)) / wavelength(L2_HZ)
        if epoch >= slip_epoch:
            high += slip_cycles
        phases.append(
            DualFrequencyPhase(
                prn=7,
                epoch=epoch,
                high_hz=L1_HZ,
                high_cycles=high,
                low_hz=L2_HZ,
                low_cycles=low,
            )
        )
    return tuple(phases)


def test_continuous_phase_reports_no_slips() -> None:
    assert detect_slips(phase_record(epoch_times(), rate=0.0)) == ()


def test_doppler_consistent_ramp_reports_no_slips() -> None:
    epochs = [0.0, 1.0, 2.5, 4.0, 8.0, 8.5, 15.0, 30.0]
    assert detect_slips(phase_record(epochs)) == ()


def test_known_step_is_detected_at_its_epoch() -> None:
    slips = detect_slips(phase_record(epoch_times(), step_cycles=STEP_CYCLES))
    assert len(slips) == 1
    assert slips[0].epoch == approx(STEP_EPOCH, abs=1e-9)
    assert slips[0].cycles == approx(STEP_CYCLES, abs=1e-9)


def test_step_below_the_threshold_is_not_reported() -> None:
    assert (
        detect_slips(
            phase_record(epoch_times(), step_cycles=0.5 * SLIP_THRESHOLD_CYCLES)
        )
        == ()
    )


def test_geometry_free_reports_a_single_cycle_slip() -> None:
    epochs = epoch_times(21)
    assert geometry_free_slips(dual_frequency(epochs)) == ()
    slips = geometry_free_slips(dual_frequency(epochs, slip_cycles=1.0))
    assert len(slips) == 1
    assert slips[0].epoch == approx(10.0, abs=1e-9)
    assert abs(slips[0].metres) == approx(wavelength(L1_HZ), abs=1e-9)
    assert abs(slips[0].metres) > GEOMETRY_FREE_THRESHOLD_METRES


def test_report_groups_slips_per_satellite() -> None:
    slips = detect_slips(
        phase_record(epoch_times(), step_cycles=STEP_CYCLES, prn=7)
        + phase_record(epoch_times(), step_cycles=STEP_CYCLES, step_epoch=90.0, prn=9)
    )
    reports = report(slips)
    assert [item.prn for item in reports] == [7, 9]
    assert reports[0].epochs == approx([STEP_EPOCH], abs=1e-9)
    assert reports[1].epochs == approx([90.0], abs=1e-9)


def test_shared_epoch_flags_a_common_mode_event() -> None:
    slips = tuple(Slip(prn=prn, epoch=10.0, cycles=0.6) for prn in (6, 12, 25, 28))
    events = common_mode_events(slips)
    assert len(events) == 1
    assert events[0].epoch == approx(10.0, abs=1e-9)
    assert events[0].prns == (6, 12, 25, 28)
    assert events[0].median_cycles == approx(0.6, abs=1e-9)


def test_isolated_slips_flag_no_common_mode_event() -> None:
    slips = (
        Slip(prn=6, epoch=10.0, cycles=0.6),
        Slip(prn=12, epoch=11.0, cycles=0.7),
    )
    assert common_mode_events(slips) == ()
