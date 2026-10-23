"""Tests the GNSS reflectometry example against ground truth."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from examples.gnss_reflectometry import (
    PEAK_TO_NOISE_THRESHOLD,
    Arc,
    ArcResult,
    HeightEstimate,
    ReflectometryJoin,
    SatelliteSample,
    SnrSample,
    assess_arc,
    join_observations,
    phase_feature,
    reflection_footprint,
    reflector_height,
    segment_arcs,
    snr_periodogram,
)
from examples.gnss_reflectometry import __main__ as reflectometry_cli
from examples.gnss_reflectometry.__main__ import (
    TRACKING_SYSTEMS,
    automatic_height,
    build_dual_payload,
    build_payload,
    reflection_coverage,
)
from examples.satellite_monitor import Constellation
from pytest import approx

from um982py.geodesy import wavelength
from um982py.messages.record import Record

L1_HZ = 1575.42e6


def rising_pass(height: float, *, amplitude: float = 3.0) -> tuple[SnrSample, ...]:
    """C/N0 in dB-Hz of a rising pass with a known reflector height in metres."""
    carrier = wavelength(L1_HZ)
    samples = []
    for index in range(241):
        elevation = 5.0 + 25.0 * index / 240
        sine = math.sin(math.radians(elevation))
        interference = amplitude * math.cos(4 * math.pi * height * sine / carrier + 0.7)
        samples.append(
            SnrSample(
                elevation=elevation,
                cn0=40.0 - 3.0 * sine + 2.0 * sine**2 + interference,
            )
        )
    return tuple(samples)


def measurement_noise(count: int, *, seed: int = 3) -> list[float]:
    """Deterministic uniform noise in dB of a C/N0 series."""
    state = seed
    values = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % 2**31
        values.append(0.4 * (state / 2**31 - 0.5))
    return values


def trend_only() -> tuple[SnrSample, ...]:
    """C/N0 of a rising pass with a smooth trend and measurement noise only."""
    samples = []
    for index, noise in enumerate(measurement_noise(241)):
        elevation = 5.0 + 25.0 * index / 240
        sine = math.sin(math.radians(elevation))
        samples.append(
            SnrSample(
                elevation=elevation, cn0=40.0 - 3.0 * sine + 2.0 * sine**2 + noise
            )
        )
    return tuple(samples)


def observation_records(
    prn: int, cn0: float, *, system: int = 0, signal: int = 0, channel: int = 7
) -> Record:
    """A minimal RANGE observation record."""
    return Record(
        name="observations",
        entries=(
            ("prn", prn),
            ("cn0", cn0),
            ("tracking_status", (system << 16) | (signal << 21) | (1 << 12)),
            ("frequency_channel", channel),
        ),
    )


def satellite_records(prn: int, elevation: float) -> Record:
    """A minimal SATVIS2 satellite record."""
    return Record(
        name="satellites",
        entries=(("prn", prn), ("elevation", elevation), ("azimuth", 135.0)),
    )


def station_sample(
    prn: int,
    time_s: float,
    elevation: float,
    azimuth: float,
    cn0: float,
    *,
    system: int = 0,
    signal: int = 0,
    frequency_hz: float = L1_HZ,
) -> SatelliteSample:
    return SatelliteSample(
        system, prn, signal, frequency_hz, time_s, elevation, azimuth, cn0
    )


def test_reflector_height_recovers_a_known_height() -> None:
    carrier = wavelength(L1_HZ)
    for height in (2.0, 3.7):
        estimate = reflector_height(rising_pass(height), wavelength_m=carrier)
        assert estimate is not None
        assert estimate.height == approx(height, abs=0.05)


def test_doubling_the_height_doubles_the_frequency() -> None:
    carrier = wavelength(L1_HZ)
    low = reflector_height(rising_pass(2.0), wavelength_m=carrier)
    high = reflector_height(rising_pass(4.0), wavelength_m=carrier)
    assert low is not None
    assert high is not None
    assert high.frequency / low.frequency == approx(2.0, rel=0.02)


def test_pure_trend_produces_no_peak() -> None:
    carrier = wavelength(L1_HZ)
    scan = snr_periodogram(trend_only(), wavelength_m=carrier)
    assert scan.peak_to_noise < PEAK_TO_NOISE_THRESHOLD
    assert reflector_height(trend_only(), wavelength_m=carrier) is None


def test_joined_elevation_series_is_monotonic_for_a_rising_pass() -> None:
    samples = [
        join_observations(
            [observation_records(5, 30.0 + index)],
            [(0, satellite_records(5, elevation))],
            time_s=float(index),
        ).samples[0]
        for index, elevation in enumerate((6.0, 11.0, 16.0, 21.0))
    ]
    elevations = [sample.elevation for sample in samples]
    assert elevations == approx([6.0, 11.0, 16.0, 21.0], abs=1e-9)


def test_all_supported_constellations_keep_their_own_wavelengths() -> None:
    signals = ((0, 0), (1, 0), (2, 0), (3, 1), (4, 0), (5, 0), (6, 6))
    joined = join_observations(
        [
            observation_records(5, 40.0, system=system, signal=signal, channel=8)
            for system, signal in signals
        ],
        [(system, satellite_records(5, 12.0)) for system, _ in signals],
        time_s=100.0,
    )
    assert {(row.system, row.signal) for row in joined.samples} == set(signals)
    glonass = next(row for row in joined.samples if row.system == 1)
    assert glonass.frequency_hz == approx(1_602_562_500.0)
    assert joined.ambiguous_satellites == ()


def test_satvis2_system_codes_map_to_range_system_codes() -> None:
    assert TRACKING_SYSTEMS[Constellation.from_value(5)] == 3
    assert TRACKING_SYSTEMS[Constellation.from_value(6)] == 4
    assert TRACKING_SYSTEMS[Constellation.from_value(7)] == 5
    assert TRACKING_SYSTEMS[Constellation.from_value(9)] == 6


def test_signals_of_one_satellite_form_separate_arcs() -> None:
    samples = [
        station_sample(5, index * 5.0, 5.0 + index, 135.0, 40.0, system=3, signal=1)
        for index in range(25)
    ]
    samples.extend(
        station_sample(
            5,
            index * 5.0,
            5.0 + index,
            135.0,
            40.0,
            system=3,
            signal=12,
            frequency_hz=1_176_450_000.0,
        )
        for index in range(25)
    )
    arcs = segment_arcs(samples, max_gap_s=15)
    assert len(arcs) == 2
    assert {arc.signal for arc in arcs} == {1, 12}


def test_separate_rising_and_setting_arcs_recover_height() -> None:
    samples = rising_pass(2.4)
    joined = [
        station_sample(5, index * 5.0, sample.elevation, 135.0, sample.cn0)
        for index, sample in enumerate(samples)
    ]
    joined.extend(
        station_sample(
            5, (index + len(samples)) * 5.0, sample.elevation, 135.0, sample.cn0
        )
        for index, sample in enumerate(reversed(samples))
    )
    arcs = segment_arcs(joined, max_gap_s=15)
    accepted = [assess_arc(arc) for arc in arcs]
    assert [row.direction for row in accepted] == ["rising", "setting"]
    assert all(row.estimate is not None for row in accepted)
    assert all(
        row.estimate.height == approx(2.4, abs=0.05) for row in accepted if row.estimate
    )


def test_arc_gap_and_azimuth_sector_are_respected() -> None:
    samples = [
        station_sample(5, index * 5.0, 5.0 + index, 350.0, 40.0) for index in range(12)
    ]
    samples.extend(
        station_sample(5, 120.0 + index * 5.0, 17.0 + index, 10.0, 40.0)
        for index in range(12)
    )
    assert (
        len(segment_arcs(samples, max_gap_s=15, azimuth_start=340, azimuth_end=20)) == 2
    )
    assert segment_arcs(samples, max_gap_s=15, azimuth_start=30, azimuth_end=90) == ()


def test_short_arc_is_rejected_without_a_height() -> None:
    samples = tuple(
        station_sample(5, index * 5.0, 5.0 + index, 90.0, 40.0) for index in range(12)
    )
    result = assess_arc(segment_arcs(samples, max_gap_s=15)[0])
    assert result.estimate is None
    assert result.rejection == "insufficient_samples"


def test_height_search_bounds_are_checked() -> None:
    with pytest.raises(ValueError, match="height bounds"):
        snr_periodogram(
            rising_pass(2.0), wavelength_m=wavelength(L1_HZ), min_height=4, max_height=1
        )


def test_report_uses_only_accepted_cn0_arcs() -> None:
    samples = tuple(
        station_sample(5, index * 5.0, sample.elevation, 135.0, sample.cn0)
        for index, sample in enumerate(rising_pass(2.4))
    )
    report = build_payload(ReflectometryJoin(samples, ()), 5, 30, 1, 6, 120, 240, 15)
    assert report["status"] == "height_estimated"
    arc = report["arcs"][0]
    assert arc["height_m"] == approx(2.4, abs=0.05)
    assert arc["rejection"] is None
    assert "phase_height_m" not in arc


def test_sparse_arc_is_rejected_before_height_search() -> None:
    samples = tuple(
        station_sample(5, index * 300.0, sample.elevation, 135.0, sample.cn0)
        for index, sample in enumerate(rising_pass(2.4)[::5])
    )
    arcs = segment_arcs(samples, max_gap_s=301)
    assert len(arcs) == 1
    result = assess_arc(arcs[0])
    assert result.rejection == "undersampled_for_max_height"


def test_reflection_footprint_follows_azimuth_and_covers_fresnel_zone() -> None:
    samples = tuple(
        station_sample(5, index * 5.0, 45.0, 90.0, 40.0) for index in range(3)
    )
    arc = segment_arcs(samples, max_gap_s=15, max_elevation=60)[0]
    footprint = reflection_footprint(arc, 2.0)
    middle = footprint["middle"]
    assert middle["specular_east_m"] == approx(2.0)
    assert middle["specular_north_m"] == approx(0.0, abs=1e-12)
    assert middle["fresnel_semimajor_m"] > middle["fresnel_semiminor_m"] > 0
    assert footprint["fresnel_bounds_m"]["east_min"] < 2.0
    assert footprint["fresnel_bounds_m"]["east_max"] > 2.0


def test_both_antennas_keep_independent_heights_and_footprints() -> None:
    samples = tuple(
        station_sample(5, index * 5.0, sample.elevation, 90.0, sample.cn0)
        for index, sample in enumerate(rising_pass(2.4))
    )
    primary = ReflectometryJoin(samples, ())
    secondary = ReflectometryJoin(samples[:12], ())
    report = build_dual_payload(primary, secondary, 5, 30, 1, 6, 0, 360, 15, None, 1.5)
    assert report["status"] == "height_estimated"
    ant1 = report["antennas"]["ANT1"]["arcs"][0]
    ant2 = report["antennas"]["ANT2"]["arcs"][0]
    assert ant1["height_m"] == approx(2.4, abs=0.05)
    assert ant1["footprint_height_source"] == "spectral_estimate"
    assert ant2["height_m"] is None
    assert ant2["footprint_height_source"] == "reference"
    assert ant2["footprint"]["reference_height_m"] == 1.5


def test_fixed_height_phase_fit_recovers_interference_phase() -> None:
    height, wavelength, phase = 12.0, 299_792_458 / 1575.42e6, 0.6
    samples = tuple(
        SnrSample(
            5 + index * 25 / 240,
            20
            * math.log10(
                100
                + 5
                * math.sin(
                    4
                    * math.pi
                    * height
                    / wavelength
                    * math.sin(math.radians(5 + index * 25 / 240))
                    + phase
                )
            ),
        )
        for index in range(241)
    )
    result = phase_feature(samples, wavelength, height)
    assert result is not None
    assert result["fit_r2"] > 0.9
    assert math.atan2(
        math.sin(result["phase_rad"] - phase),
        math.cos(result["phase_rad"] - phase),
    ) == approx(0.0, abs=0.1)


def test_automatic_height_counts_distinct_satellite_tracks() -> None:
    def result(prn: int, signal: int, height: float) -> ArcResult:
        return ArcResult(
            0,
            prn,
            signal,
            L1_HZ,
            "rising",
            100,
            1200.0,
            20.0,
            HeightEstimate(height, 2 * height / wavelength(L1_HZ), 4.0),
            None,
        )

    first = automatic_height([result(5, 0, 2.0), result(5, 9, 2.2)])
    assert first["distinct_tracks"] == 1
    assert first["height_m"] == approx(2.1)
    assert first["status"] == "provisional"
    consensus = automatic_height(
        [result(5, 0, 2.0), result(7, 0, 2.1), result(9, 0, 1.9)]
    )
    assert consensus["height_m"] == approx(2.0)
    assert consensus["status"] == "consensus"
    assert automatic_height([result(5, 0, 2.0), result(7, 0, 4.0)])["status"] == (
        "inconsistent"
    )


def test_reflection_coverage_reports_only_observed_successful_sectors() -> None:
    samples = tuple(
        station_sample(5, index * 5.0, 10.0 + index, 62.0, 40.0) for index in range(3)
    )
    arcs = (
        Arc(0, 5, 0, L1_HZ, "rising", samples),
        Arc(0, 7, 0, L1_HZ, "rising", samples),
    )
    results = tuple(
        ArcResult(
            arc.system,
            arc.prn,
            arc.signal,
            arc.frequency_hz,
            arc.direction,
            100,
            1200.0,
            20.0,
            HeightEstimate(2.0, 20.0, 4.0),
            None,
        )
        for arc in arcs
    )
    sector = reflection_coverage(arcs, results)[0]
    assert sector["azimuth_start_deg"] == 60
    assert sector["azimuth_end_deg"] == 90
    assert sector["elevation_min_deg"] == approx(10.0)
    assert sector["elevation_max_deg"] == approx(12.0)
    assert sector["accepted_distinct_tracks"] == 2
    assert sector["status"] == "multiple_tracks"


def test_debug_console_reports_arc_decisions_without_mixing_with_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    accepted = tuple(
        station_sample(5, index * 5.0, sample.elevation, 135.0, sample.cn0)
        for index, sample in enumerate(rising_pass(2.4))
    )
    rejected = tuple(
        station_sample(7, index * 5.0, 5.0 + index, 90.0, 40.0) for index in range(12)
    )
    joins = iter(
        (
            ReflectometryJoin(accepted, ((0, 9),), {"missing_geometry": 2}),
            ReflectometryJoin(rejected, ()),
        )
    )
    monkeypatch.setattr(
        reflectometry_cli,
        "capture_records",
        lambda *_args, **_kwargs: {"RANGE": (), "RANGEH": (), "SATVIS2": ()},
    )
    monkeypatch.setattr(
        reflectometry_cli, "epoch_samples", lambda *_args, **_kwargs: next(joins)
    )
    output = tmp_path / "heights.json"
    assert reflectometry_cli.main(["--debug", "--json", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "decoded records: RANGE=0, RANGEH=0, SATVIS2=0" in captured.err
    assert "ANT1: RANGE epochs=0, joined samples=241" in captured.err
    assert "ambiguous satellites=1, omitted={'missing_geometry': 2}" in captured.err
    assert "GPS 5" in captured.err
    assert "height=" in captured.err
    assert "rejected=insufficient_samples" in captured.err
    assert f"JSON={output}" in captured.err
    assert '"status": "height_estimated"' in output.read_text(encoding="utf-8")


def test_debug_console_is_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        reflectometry_cli,
        "capture_records",
        lambda *_args, **_kwargs: {"RANGE": (), "RANGEH": (), "SATVIS2": ()},
    )
    assert reflectometry_cli.main(["--json", str(tmp_path / "empty.json")]) == 1
    assert capsys.readouterr().err == ""
