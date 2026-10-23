"""Summarize GNSS-IR arcs, observed sectors and repeat-pass phase changes."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from statistics import median
from typing import cast

from examples.gnss_reflectometry import (
    MINIMUM_ELEVATION_SPAN,
    MINIMUM_SAMPLES,
    PEAK_TO_NOISE_THRESHOLD,
    SPEED_OF_LIGHT,
    Arc,
    ArcResult,
    ReflectometryJoin,
    SnrSample,
    assess_arc,
    phase_feature,
    reflection_footprint,
    segment_arcs,
)
from um982py.signals import tracking_signal


@dataclass(frozen=True, slots=True)
class QualityCriteria:
    threshold: float = PEAK_TO_NOISE_THRESHOLD
    min_samples: int = MINIMUM_SAMPLES
    min_span: float = MINIMUM_ELEVATION_SPAN
    min_duration: float = 60.0
    min_amplitude: float = 0.0
    min_fit_r2: float = 0.0
    include_spectra: bool = False


def signal_labels(system: int, signal: int) -> tuple[str, str]:
    identity = tracking_signal((system << 16) | (signal << 21))
    return (
        (identity.constellation, identity.name)
        if identity
        else (str(system), str(signal))
    )


def automatic_height(results: Sequence[ArcResult]) -> dict[str, object]:
    """Aggregate satellites equally, without counting each frequency as a track."""
    groups: dict[tuple[int, int, str], list[float]] = defaultdict(list)
    for result in results:
        if result.estimate is not None and result.rejection is None:
            groups[result.system, result.prn, result.direction].append(
                result.estimate.height
            )
    values = [median(heights) for heights in groups.values()]
    if not values:
        return {"status": "unavailable", "height_m": None, "distinct_tracks": 0}
    height = median(values)
    spread = max(values) - min(values)
    consistent = spread <= max(0.5, 0.2 * height)
    return {
        "status": "inconsistent"
        if not consistent
        else "consensus"
        if len(values) >= 3
        else "provisional",
        "height_m": height,
        "distinct_tracks": len(values),
        "track_mad_m": median(abs(value - height) for value in values),
        "track_range_m": spread,
    }


def reflection_coverage(
    arcs: Sequence[Arc], results: Sequence[ArcResult]
) -> list[dict[str, object]]:
    sectors: dict[int, list[Arc]] = defaultdict(list)
    for arc, result in zip(arcs, results, strict=True):
        if result.estimate is not None and result.rejection is None:
            for sector in {int(sample.azimuth % 360 // 30) for sample in arc.samples}:
                sectors[sector].append(arc)
    output: list[dict[str, object]] = []
    for sector, rows in sorted(sectors.items()):
        tracks = {(arc.system, arc.prn, arc.direction) for arc in rows}
        elevations = [
            sample.elevation
            for arc in rows
            for sample in arc.samples
            if int(sample.azimuth % 360 // 30) == sector
        ]
        output.append(
            {
                "azimuth_start_deg": sector * 30,
                "azimuth_end_deg": (sector + 1) * 30,
                "elevation_min_deg": min(elevations),
                "elevation_max_deg": max(elevations),
                "accepted_distinct_tracks": len(tracks),
                "status": "multiple_tracks" if len(tracks) >= 2 else "single_track",
            }
        )
    return output


def _arc_summary(
    arc: Arc, result: ArcResult, reference_height: float | None, include_spectra: bool
) -> dict[str, object]:
    height = result.estimate.height if result.estimate else None
    footprint_height = reference_height if reference_height is not None else height
    constellation, signal = signal_labels(arc.system, arc.signal)
    azimuth = (
        math.degrees(
            math.atan2(
                sum(math.sin(math.radians(row.azimuth)) for row in arc.samples),
                sum(math.cos(math.radians(row.azimuth)) for row in arc.samples),
            )
        )
        % 360
    )
    spectrum = result.spectrum
    output: dict[str, object] = {
        "system": arc.system,
        "constellation": constellation,
        "prn": arc.prn,
        "signal": arc.signal,
        "signal_name": signal,
        "l2c_flag": arc.l2c_flag,
        "frequency_hz": arc.frequency_hz,
        "wavelength_m": SPEED_OF_LIGHT / arc.frequency_hz,
        "direction": arc.direction,
        "samples": result.sample_count,
        "start_gps_s": arc.samples[0].time_s,
        "end_gps_s": arc.samples[-1].time_s,
        "duration_s": result.duration_s,
        "elevation_span_deg": result.elevation_span_deg,
        "elevation_min_deg": min(row.elevation for row in arc.samples),
        "elevation_max_deg": max(row.elevation for row in arc.samples),
        "azimuth_mean_deg": azimuth,
        "median_cn0_db_hz": median(row.cn0 for row in arc.samples),
        "height_m": height,
        "reference_error_m": height - reference_height
        if height is not None and reference_height is not None
        else None,
        "peak_to_noise": spectrum.peak_to_noise if spectrum else None,
        "height_resolution_m": spectrum.height_resolution_m if spectrum else None,
        "rejection": result.rejection,
        "spectral_fit": result.fit,
        "reference_phase": phase_feature(
            [SnrSample(row.elevation, row.cn0) for row in arc.samples],
            SPEED_OF_LIGHT / arc.frequency_hz,
            reference_height,
        )
        if reference_height is not None
        else None,
        "footprint_height_source": "reference"
        if reference_height is not None
        else "spectral_estimate"
        if height is not None
        else None,
        "footprint": reflection_footprint(arc, footprint_height)
        if footprint_height is not None
        else None,
    }
    if include_spectra and spectrum is not None:
        output["spectrum"] = [
            {
                "height_m": SPEED_OF_LIGHT * frequency / (2 * arc.frequency_hz),
                "lomb_power": power,
            }
            for frequency, power in zip(
                spectrum.frequencies, spectrum.powers, strict=True
            )
        ]
    return output


def build_payload(
    joined: ReflectometryJoin,
    min_elevation: float,
    max_elevation: float,
    min_height: float,
    max_height: float,
    azimuth_start: float,
    azimuth_end: float,
    max_gap: float,
    reference_height: float | None = None,
    *,
    quality: QualityCriteria | None = None,
) -> dict[str, object]:
    quality = quality or QualityCriteria()
    if reference_height is not None and (
        not math.isfinite(reference_height) or reference_height <= 0
    ):
        raise ValueError("reference height must be finite and positive")
    arcs = segment_arcs(
        joined.samples,
        max_gap_s=max_gap,
        min_elevation=min_elevation,
        max_elevation=max_elevation,
        azimuth_start=azimuth_start,
        azimuth_end=azimuth_end,
    )
    results = tuple(
        assess_arc(
            arc,
            min_height=min_height,
            max_height=max_height,
            threshold=quality.threshold,
            min_samples=quality.min_samples,
            min_span=quality.min_span,
            min_duration=quality.min_duration,
            min_amplitude=quality.min_amplitude,
            min_fit_r2=quality.min_fit_r2,
        )
        for arc in arcs
    )
    accepted = sum(result.estimate is not None for result in results)
    return {
        "status": "height_estimated"
        if accepted
        else "insufficient_arc"
        if joined.samples
        else "no_synchronized_samples",
        "samples": len(joined.samples),
        "accepted_arcs": accepted,
        "ambiguous_satellites": joined.ambiguous_satellites,
        "omitted": joined.omitted,
        "rejection_counts": dict(
            Counter(result.rejection for result in results if result.rejection)
        ),
        "automatic_height": automatic_height(results),
        "observed_sectors": reflection_coverage(arcs, results),
        "arcs": [
            _arc_summary(arc, result, reference_height, quality.include_spectra)
            for arc, result in zip(arcs, results, strict=True)
        ],
    }


def build_dual_payload(
    primary: ReflectometryJoin,
    secondary: ReflectometryJoin,
    min_elevation: float,
    max_elevation: float,
    min_height: float,
    max_height: float,
    azimuth_start: float,
    azimuth_end: float,
    max_gap: float,
    reference_height_ant1: float | None = None,
    reference_height_ant2: float | None = None,
    *,
    quality: QualityCriteria | None = None,
) -> dict[str, object]:
    quality = quality or QualityCriteria()
    antennas = {
        antenna: build_payload(
            joined,
            min_elevation,
            max_elevation,
            min_height,
            max_height,
            azimuth_start,
            azimuth_end,
            max_gap,
            reference,
            quality=quality,
        )
        for antenna, joined, reference in (
            ("ANT1", primary, reference_height_ant1),
            ("ANT2", secondary, reference_height_ant2),
        )
    }
    return {
        "schema_version": 1,
        "method": "GNSS-IR C/N0 interferometry",
        "status": "height_estimated"
        if any(row["accepted_arcs"] for row in antennas.values())
        else "insufficient_arc"
        if primary.samples or secondary.samples
        else "no_synchronized_samples",
        "parameters": {
            "min_elevation_deg": min_elevation,
            "max_elevation_deg": max_elevation,
            "min_height_m": min_height,
            "max_height_m": max_height,
            "azimuth_start_deg": azimuth_start,
            "azimuth_end_deg": azimuth_end,
            "max_gap_s": max_gap,
            "quality": asdict(quality),
        },
        "antennas": antennas,
    }


def compare_reference(
    current: Mapping[str, object], reference: Mapping[str, object]
) -> list[dict[str, object]]:
    """Compare accepted phase fits at the same measured height and geometry."""
    output: list[dict[str, object]] = []
    before = reference.get("antennas")
    after = current.get("antennas")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("reference JSON needs per-antenna arc reports")
    keys = ("system", "prn", "signal", "l2c_flag", "frequency_hz", "direction")
    for antenna, report in after.items():
        earlier = before.get(antenna, {})
        if not isinstance(report, dict) or not isinstance(earlier, dict):
            raise ValueError("invalid antenna report in reference JSON")
        for raw in report.get("arcs", []):
            row = cast(dict[str, object], raw)
            fit = row.get("reference_phase")
            if (
                row.get("rejection") is not None
                or not isinstance(fit, dict)
                or float(fit["fit_r2"]) < 0.7
            ):
                continue
            candidates: list[dict[str, object]] = []
            for old_raw in earlier.get("arcs", []):
                old = cast(dict[str, object], old_raw)
                previous = old.get("reference_phase")
                if (
                    old.get("rejection") is not None
                    or not isinstance(previous, dict)
                    or float(previous["fit_r2"]) < 0.7
                    or any(row[key] != old.get(key) for key in keys)
                ):
                    continue
                if (
                    abs(
                        float(fit["reference_height_m"])
                        - float(previous["reference_height_m"])
                    )
                    > 1e-6
                ):
                    continue
                azimuth_difference = abs(
                    (
                        cast(float, row["azimuth_mean_deg"])
                        - cast(float, old["azimuth_mean_deg"])
                        + 180
                    )
                    % 360
                    - 180
                )
                overlap = min(
                    cast(float, row["elevation_max_deg"]),
                    cast(float, old["elevation_max_deg"]),
                ) - max(
                    cast(float, row["elevation_min_deg"]),
                    cast(float, old["elevation_min_deg"]),
                )
                span = max(
                    cast(float, row["elevation_span_deg"]),
                    cast(float, old["elevation_span_deg"]),
                )
                if azimuth_difference <= 5 and overlap >= 0.8 * span:
                    candidates.append(old)
            if len(candidates) != 1:
                continue
            previous = cast(dict[str, float], candidates[0]["reference_phase"])
            delta = float(fit["phase_rad"]) - previous["phase_rad"]
            output.append(
                {
                    "antenna": antenna,
                    **{key: row[key] for key in keys},
                    "start_gps_s": row["start_gps_s"],
                    "reference_start_gps_s": candidates[0]["start_gps_s"],
                    "phase_change_rad": math.atan2(math.sin(delta), math.cos(delta)),
                }
            )
    return output
