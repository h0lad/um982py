"""Tests the multipath analysis example against ground truth."""

from __future__ import annotations

import math
from collections.abc import Callable

from examples.multipath_analysis import (
    Observation,
    epoch_summaries,
    multipath_series,
)
from pytest import approx

from um982py.geodesy import wavelength

L1_HZ = 1575.42e6
CARRIER = wavelength(L1_HZ)
GEOMETRY_METRES = 22_000_000.0
RANGE_RATE = 300.0
AMBIGUITY_CYCLES = 12
SINUSOID_METRES = 1.5
SINUSOID_PERIOD_SECONDS = 300.0


def synthetic(
    multipath: Callable[[float], float] = lambda epoch: 0.0,
    *,
    prn: int = 7,
    count: int = 1201,
) -> tuple[Observation, ...]:
    """Pseudorange from carrier phase plus a constant ambiguity and a multipath term."""
    observations = []
    for index in range(count):
        epoch = float(index)
        geometry = GEOMETRY_METRES + RANGE_RATE * epoch
        carrier_range = geometry + AMBIGUITY_CYCLES * CARRIER
        observations.append(
            Observation(
                prn=prn,
                epoch=epoch,
                frequency_hz=L1_HZ,
                pseudorange=geometry + multipath(epoch),
                carrier_phase=-carrier_range / CARRIER,
            )
        )
    return tuple(observations)


def sinusoid(epoch: float) -> float:
    """Multipath in metres with a known amplitude and period."""
    return SINUSOID_METRES * math.cos(
        2 * math.pi * epoch / SINUSOID_PERIOD_SECONDS + 0.4
    )


def test_clean_pseudorange_leaves_no_residual() -> None:
    series = multipath_series(synthetic())
    assert len(series) == 1
    assert series[0].rms == approx(0.0, abs=1e-6)
    assert list(series[0].residuals) == approx(
        [0.0] * len(series[0].residuals), abs=1e-6
    )


def test_injected_sinusoid_reports_amplitude_over_root_two() -> None:
    series = multipath_series(synthetic(sinusoid))
    expected = SINUSOID_METRES / math.sqrt(2)
    assert series[0].rms == approx(expected, rel=0.05)


def test_epoch_summary_covers_every_signal() -> None:
    observations = synthetic() + synthetic(prn=9)
    summaries = epoch_summaries(multipath_series(observations))
    first = summaries[0]
    assert first.signals == 2
    assert first.rms == approx(0.0, abs=1e-6)
    assert first.maximum == approx(0.0, abs=1e-6)
