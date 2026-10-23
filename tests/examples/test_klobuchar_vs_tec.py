"""Tests the Klobuchar versus TEC example against ground truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from examples.ionosphere_tec import (
    Observation,
)
from examples.klobuchar_vs_tec import (
    GPS_L1_HZ,
    IONOSPHERE_COEFFICIENT,
    NIGHT_TIME_DELAY_SECONDS,
    TECU,
    KlobucharCoefficients,
    diurnal_profile,
    local_solar_seconds,
    measured_vertical_delay,
    obliquity_factor,
    vertical_delay_from_slant_tec,
    vertical_delay_metres,
    vertical_delay_seconds,
)

from um982py.commands import Log
from um982py.geodesy import SPEED_OF_LIGHT, wavelength
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures-live"
EPOCH_SECONDS = 399_541.0
L5_HZ = 1176.45e6
LATITUDE = 52.5336647
LONGITUDE = 13.3763266
GEOMETRY_METRES = 20_000_000.0
INJECTED_TEC = 42.5


def live_coefficients() -> KlobucharCoefficients:
    """GPSION coefficients captured at the live epoch."""
    record = next(
        Log.GPSION.decode(message)
        for message in StreamDecoder().feed((FIXTURES / "GPSIONA.bin").read_bytes())
        if getattr(message, "name", "").startswith("GPSIONA")
    )
    return KlobucharCoefficients.from_record(record)


def injected_observations(tec_tecu: float) -> tuple[Observation, ...]:
    """Dual-frequency observations for a known slant TEC."""

    def delay(frequency_hz: float) -> float:
        return IONOSPHERE_COEFFICIENT * tec_tecu * TECU / frequency_hz**2

    return (
        Observation(
            prn=7,
            frequency_hz=GPS_L1_HZ,
            pseudorange=GEOMETRY_METRES + delay(GPS_L1_HZ),
            carrier_phase=-(GEOMETRY_METRES - delay(GPS_L1_HZ)) / wavelength(GPS_L1_HZ),
        ),
        Observation(
            prn=7,
            frequency_hz=L5_HZ,
            pseudorange=GEOMETRY_METRES + delay(L5_HZ),
            carrier_phase=-(GEOMETRY_METRES - delay(L5_HZ)) / wavelength(L5_HZ),
        ),
    )


def test_coefficients_match_the_live_capture() -> None:
    record = next(
        Log.GPSION.decode(message)
        for message in StreamDecoder().feed((FIXTURES / "GPSIONA.bin").read_bytes())
        if getattr(message, "name", "").startswith("GPSIONA")
    )
    coefficients = KlobucharCoefficients.from_record(record)
    assert coefficients.a0 == pytest.approx(record.real("a0"), abs=0.0)
    assert coefficients.a1 == pytest.approx(record.real("a1"), abs=0.0)
    assert coefficients.a2 == pytest.approx(record.real("a2"), abs=0.0)
    assert coefficients.a3 == pytest.approx(record.real("a3"), abs=0.0)
    assert coefficients.b0 == pytest.approx(record.real("b0"), abs=0.0)
    assert coefficients.b1 == pytest.approx(record.real("b1"), abs=0.0)
    assert coefficients.b2 == pytest.approx(record.real("b2"), abs=0.0)
    assert coefficients.b3 == pytest.approx(record.real("b3"), abs=0.0)


def test_obliquity_factor_matches_the_closed_form() -> None:
    assert obliquity_factor(0.0) == pytest.approx(3.382032, abs=1e-6)
    assert obliquity_factor(90.0) == pytest.approx(1.000432, abs=1e-6)


def test_zero_amplitude_keeps_the_night_time_delay() -> None:
    coefficients = KlobucharCoefficients(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    seconds = vertical_delay_seconds(
        coefficients,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        elevation=45.0,
        azimuth=180.0,
        gps_seconds=EPOCH_SECONDS,
    )
    assert seconds == pytest.approx(NIGHT_TIME_DELAY_SECONDS, rel=1e-12)
    metres = vertical_delay_metres(
        coefficients,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        elevation=45.0,
        azimuth=180.0,
        gps_seconds=EPOCH_SECONDS,
    )
    assert metres == pytest.approx(SPEED_OF_LIGHT * NIGHT_TIME_DELAY_SECONDS, abs=1e-6)


def test_diurnal_delay_peaks_in_the_local_afternoon() -> None:
    profile = diurnal_profile(
        live_coefficients(),
        latitude=LATITUDE,
        longitude=LONGITUDE,
        elevation=45.0,
        azimuth=180.0,
        start_seconds=EPOCH_SECONDS,
    )
    peak_seconds, peak_delay = max(profile, key=lambda sample: sample[1])
    minimum_delay = min(sample[1] for sample in profile)
    assert 12.0 <= peak_seconds / 3600.0 <= 18.0
    assert peak_delay > minimum_delay
    assert peak_delay > 2.0 * minimum_delay


def test_local_solar_time_wraps_at_the_day_boundary() -> None:
    assert local_solar_seconds(39_600.0, 15.0) == pytest.approx(43_200.0, abs=1e-9)
    assert local_solar_seconds(86_000.0, 15.0) == pytest.approx(3_200.0, abs=1e-9)


def test_measured_vertical_delay_recovers_an_injected_slant_tec() -> None:
    observations = injected_observations(INJECTED_TEC)
    measured = measured_vertical_delay(observations, 45.0)
    assert measured is not None
    expected = vertical_delay_from_slant_tec(INJECTED_TEC, 45.0)
    zenith_delay = IONOSPHERE_COEFFICIENT * INJECTED_TEC * TECU / GPS_L1_HZ**2
    assert measured == pytest.approx(expected, abs=1e-9)
    assert measured * obliquity_factor(45.0) == pytest.approx(zenith_delay, abs=1e-9)


def test_unpaired_observations_yield_no_measured_delay() -> None:
    single = injected_observations(INJECTED_TEC)[:1]
    assert measured_vertical_delay(single, 45.0) is None


def test_invalid_elevation_is_rejected() -> None:
    with pytest.raises(ValueError, match="elevation"):
        obliquity_factor(-1.0)
