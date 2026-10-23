"""Tests the ionosphere TEC example against ground truth."""

from __future__ import annotations

from collections.abc import Sequence

from examples.ionosphere_tec import (
    TECU,
    TECU_PER_METRE,
    Observation,
    TecRate,
    TecSample,
    level_tec,
    phase_tec,
    rate_of_tec,
    roti,
    slant_tec,
)
from pytest import approx

from um982py.geodesy import wavelength
from um982py.stats import stddev

L1_HZ = 1575.42e6
L2_HZ = 1227.60e6
COEFFICIENT = 40.3
GEOMETRY_METRES = 20_000_000.0


def delay(frequency_hz: float, tec: float) -> float:
    """Group delay in metres of a slant TEC in TECU at a frequency."""
    return COEFFICIENT * tec * TECU / frequency_hz**2


def tec_scale() -> float:
    """TECU per metre of differential code delay, from the published constants."""
    return L1_HZ**2 * L2_HZ**2 / ((L1_HZ**2 - L2_HZ**2) * COEFFICIENT * TECU)


def observations(
    tec: float, ambiguity: tuple[int, int] = (0, 0)
) -> tuple[Observation, ...]:
    """Dual-frequency observations of PRN 7 for a known slant TEC."""
    l1_phase = -(
        GEOMETRY_METRES - delay(L1_HZ, tec) + ambiguity[0] * wavelength(L1_HZ)
    ) / wavelength(L1_HZ)
    l2_phase = -(
        GEOMETRY_METRES - delay(L2_HZ, tec) + ambiguity[1] * wavelength(L2_HZ)
    ) / wavelength(L2_HZ)
    return (
        Observation(
            prn=7,
            frequency_hz=L1_HZ,
            pseudorange=GEOMETRY_METRES + delay(L1_HZ, tec),
            carrier_phase=l1_phase,
        ),
        Observation(
            prn=7,
            frequency_hz=L2_HZ,
            pseudorange=GEOMETRY_METRES + delay(L2_HZ, tec),
            carrier_phase=l2_phase,
        ),
    )


def code_tec(pair: Sequence[Observation]) -> float:
    """Code TEC of a paired observation set, failing the test when unpaired."""
    value = slant_tec(pair)
    assert value is not None
    return value


def carrier_tec(pair: Sequence[Observation]) -> float:
    """Carrier TEC of a paired observation set, failing the test when unpaired."""
    value = phase_tec(pair)
    assert value is not None
    return value


def tec_samples(
    values: Sequence[float], *, interval: float = 30.0
) -> tuple[TecSample, ...]:
    """One satellite sampled at a constant interval."""
    return tuple(
        TecSample(prn=7, epoch=index * interval, tec=tec)
        for index, tec in enumerate(values)
    )


def test_code_tec_recovers_the_injected_tec() -> None:
    assert code_tec(observations(42.5)) == approx(42.5, abs=1e-6)


def test_tec_scale_matches_the_published_tec_per_metre() -> None:
    assert approx(9.5196, rel=1e-4) == TECU_PER_METRE
    assert approx(tec_scale(), rel=1e-12) == TECU_PER_METRE


def test_one_tecu_is_the_published_differential_delay() -> None:
    published = COEFFICIENT * TECU * (1 / L2_HZ**2 - 1 / L1_HZ**2)
    assert published == approx(0.105046, abs=1e-6)
    assert approx(published, abs=1e-12) == 1 / TECU_PER_METRE


def test_phase_tec_carries_the_ambiguity() -> None:
    tec = 31.25
    pair = observations(tec, ambiguity=(5, -3))
    assert code_tec(pair) == approx(tec, abs=1e-6)
    ambiguity_metres = 5 * wavelength(L1_HZ) + 3 * wavelength(L2_HZ)
    assert carrier_tec(pair) - tec == approx(tec_scale() * ambiguity_metres, abs=1e-6)


def test_levelling_removes_the_ambiguity() -> None:
    pairs = [observations(tec, ambiguity=(11, 4)) for tec in (10.0, 14.0, 21.0, 19.0)]
    code = [code_tec(pair) for pair in pairs]
    carrier = [carrier_tec(pair) for pair in pairs]
    assert level_tec(code, carrier) == approx(code, abs=1e-6)


def test_constant_tec_gives_zero_roti() -> None:
    rates = rate_of_tec(tec_samples([25.0] * 21))
    assert [rate.rate for rate in rates] == approx([0.0] * 20, abs=1e-12)
    assert [index.index for index in roti(rates)] == approx([0.0] * 19, abs=1e-12)


def test_linear_ramp_reproduces_the_ramp_rate() -> None:
    ramp_rate = 2.5
    values = [12.0 + ramp_rate * index / 2 for index in range(21)]
    rates = rate_of_tec(tec_samples(values))
    assert [rate.rate for rate in rates] == approx([ramp_rate] * 20, abs=1e-12)


def test_roti_is_the_standard_deviation_of_rot() -> None:
    rates = (
        TecRate(prn=7, epoch=30.0, rate=0.0),
        TecRate(prn=7, epoch=60.0, rate=0.2),
        TecRate(prn=7, epoch=90.0, rate=0.4),
    )
    assert roti(rates)[-1].index == approx(stddev([0.0, 0.2, 0.4]), abs=1e-12)


def test_payload_includes_carrier_levelled_tec_and_phase_roti() -> None:
    from examples.ionosphere_tec.__main__ import build_payload

    code = tec_samples([20.0, 21.0, 22.0], interval=60.0)
    phase = tec_samples([-100.0, -99.0, -98.0], interval=60.0)
    payload = build_payload(code, 1, L1_HZ, phase_samples=phase)
    levelled = payload["levelled_tec"]
    assert isinstance(levelled, list)
    assert [row["tec"] for row in levelled] == approx([20.0, 21.0, 22.0], abs=1e-9)
    phase_rot = payload["phase_rot"]
    assert isinstance(phase_rot, list)
    assert [row["rate"] for row in phase_rot] == approx([1.0, 1.0], abs=1e-9)
