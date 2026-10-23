"""Tests the compressed observation audit example."""

from __future__ import annotations

import pytest
from examples.compressed_observation_audit import (
    agree_epoch,
    summarise_epochs,
)

from um982py.experimental import CompressedObservation
from um982py.messages import Record


def observation(
    status: int,
    pseudorange: float,
    doppler: float,
    phase: float,
) -> Record:
    """Build one synthetic RANGE observation record."""
    return Record(
        "observation",
        (
            ("tracking_status", status),
            ("pseudorange", pseudorange),
            ("doppler", doppler),
            ("carrier_phase", phase),
        ),
    )


def compressed(
    status: int,
    pseudorange: float,
    doppler: float,
    phase: float | None,
    saturated: bool = False,
) -> CompressedObservation:
    """Build one synthetic compressed observation."""
    return CompressedObservation(
        tracking_status=status,
        prn=7,
        doppler_hz=doppler,
        pseudorange_m=pseudorange,
        carrier_phase_cycles=phase,
        pseudorange_std_m=0.380,
        carrier_phase_std_cycles=0.004,
        lock_time_s=120.0,
        cn0_db_hz=20 if saturated else 35,
        cn0_saturated=saturated,
        glonass_channel=0,
        divergence_cycles=1.5 if phase is not None else None,
    )


def lookup(*observations: Record) -> dict[int, Record]:
    """Index synthetic observations by tracking status."""
    return {
        observation.integer("tracking_status"): observation
        for observation in observations
    }


def test_shared_status_scores_residuals() -> None:
    reference = observation(0x43, 20234567.125, -1234.5, -98765432.0)
    compressed_observation = compressed(0x43, 20234567.1, -1234.4, -98765431.9)
    agreement = agree_epoch(
        lookup(reference),
        (compressed_observation,),
        range_bytes=1000,
        compressed_bytes=600,
    )
    assert agreement.matched == 1
    assert agreement.unmatched == 0
    assert agreement.worst_pseudorange_m == pytest.approx(0.025)
    assert agreement.worst_doppler_hz == pytest.approx(0.1)
    assert agreement.worst_phase_cycles == pytest.approx(0.1)
    assert agreement.saturated_cn0 == 0
    assert (agreement.range_bytes, agreement.compressed_bytes) == (1000, 600)


def test_unknown_status_counts_as_unmatched() -> None:
    agreement = agree_epoch(
        lookup(observation(0x43, 20234567.0, 0.0, 0.0)),
        (compressed(0x44, 20234567.0, 0.0, 0.0),),
        range_bytes=100,
        compressed_bytes=60,
    )
    assert (agreement.matched, agreement.unmatched) == (0, 1)
    assert agreement.worst_phase_cycles is None


def test_missing_phase_skips_the_phase_residual() -> None:
    reference = observation(0x43, 20234567.0, 0.0, -100.0)
    agreement = agree_epoch(
        lookup(reference),
        (compressed(0x43, 20234567.0, 0.0, None),),
        range_bytes=100,
        compressed_bytes=60,
    )
    assert agreement.matched == 1
    assert agreement.worst_phase_cycles is None


def test_saturated_cn0_counts_separately() -> None:
    reference = observation(0x43, 20234567.0, 0.0, 0.0)
    observations = (
        compressed(0x43, 20234567.0, 0.0, 0.0),
        compressed(0x43, 20234567.0, 0.0, 0.0, saturated=True),
    )
    agreement = agree_epoch(
        lookup(reference), observations, range_bytes=100, compressed_bytes=60
    )
    assert agreement.saturated_cn0 == 1


def test_summary_combines_epochs_with_wire_ratio() -> None:
    first = agree_epoch(
        lookup(observation(0x43, 20234567.0, 0.0, 0.0)),
        (compressed(0x43, 20234567.05, 0.02, 0.03),),
        range_bytes=1000,
        compressed_bytes=600,
    )
    second = agree_epoch(
        lookup(observation(0x44, 20234568.0, 1.0, 1.0)),
        (compressed(0x44, 20234568.5, 1.5, None),),
        range_bytes=1000,
        compressed_bytes=600,
    )
    summary = summarise_epochs((first, second))
    assert summary.epochs == 2
    assert summary.matched == 2
    assert summary.worst_pseudorange_m == pytest.approx(0.5)
    assert summary.worst_doppler_hz == pytest.approx(0.5)
    assert summary.worst_phase_cycles == pytest.approx(0.03)
    assert (summary.range_bytes, summary.compressed_bytes) == (2000, 1200)
    assert summary.ratio == pytest.approx(0.6)


def test_empty_summary_has_zero_ratio() -> None:
    summary = summarise_epochs(())
    assert summary.epochs == 0
    assert summary.matched == 0
    assert summary.worst_phase_cycles is None
    assert summary.ratio == pytest.approx(0.0)
