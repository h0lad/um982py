"""Analyze multi-GNSS C/N0 arcs, reflector heights and reflection footprints."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from um982py.messages.record import Record
from um982py.signals import tracking_signal
from um982py.stats import detrend, finite, least_squares, lomb_scargle, mean

SPEED_OF_LIGHT = 299_792_458.0
MIN_ELEVATION_DEGREES = 5.0
MAX_ELEVATION_DEGREES = 30.0
MIN_HEIGHT_METRES = 1.0
MAX_HEIGHT_METRES = 6.0
PEAK_TO_NOISE_THRESHOLD = 2.7
FREQUENCY_OVERSAMPLE = 8
DETREND_ORDER = 2
MINIMUM_SAMPLES = 20
MINIMUM_ELEVATION_SPAN = 5.0


@dataclass(frozen=True, slots=True)
class SnrSample:
    elevation: float
    cn0: float


@dataclass(frozen=True, slots=True)
class SatelliteSample:
    system: int
    prn: int
    signal: int
    frequency_hz: float
    time_s: float
    elevation: float
    azimuth: float
    cn0: float
    lock_seconds: float | None = None
    l2c_flag: bool = False


@dataclass(frozen=True, slots=True)
class ReflectometryJoin:
    samples: tuple[SatelliteSample, ...]
    ambiguous_satellites: tuple[tuple[int, int], ...]
    omitted: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Periodogram:
    frequencies: tuple[float, ...]
    powers: tuple[float, ...]
    peak_frequency: float
    peak_power: float
    noise_power: float
    height_resolution_m: float

    @property
    def peak_to_noise(self) -> float:
        return (
            math.sqrt(self.peak_power / self.noise_power)
            if self.noise_power > 0
            else 0.0
        )


@dataclass(frozen=True, slots=True)
class HeightEstimate:
    height: float
    frequency: float
    peak_to_noise: float


@dataclass(frozen=True, slots=True)
class Arc:
    system: int
    prn: int
    signal: int
    frequency_hz: float
    direction: str
    samples: tuple[SatelliteSample, ...]
    l2c_flag: bool = False


@dataclass(frozen=True, slots=True)
class ArcResult:
    system: int
    prn: int
    signal: int
    frequency_hz: float
    direction: str
    sample_count: int
    duration_s: float
    elevation_span_deg: float
    estimate: HeightEstimate | None
    rejection: str | None
    spectrum: Periodogram | None = None
    fit: dict[str, float] | None = None


def join_observations(
    observations: Iterable[Record],
    satellites: Iterable[tuple[int, Record]],
    *,
    time_s: float,
) -> ReflectometryJoin:
    """Join RANGE identities to unambiguous, same-epoch satellite geometry."""
    finite(time_s)
    geometry: dict[tuple[int, int], set[tuple[float, float]]] = defaultdict(set)
    omitted: Counter[str] = Counter()
    for system, satellite in satellites:
        elevation, azimuth = satellite.real("elevation"), satellite.real("azimuth")
        if math.isfinite(elevation) and math.isfinite(azimuth) and 0 < elevation < 90:
            geometry[system, satellite.integer("prn")].add((elevation, azimuth % 360))
    ambiguous = tuple(
        sorted(key for key, values in geometry.items() if len(values) > 1)
    )
    selected: dict[tuple[int, int, int, bool], SatelliteSample] = {}
    for observation in observations:
        status = observation.integer("tracking_status")
        system, signal = status >> 16 & 7, status >> 21 & 31
        prn, cn0 = observation.integer("prn"), observation.real("cn0")
        if not status & (1 << 12) or not math.isfinite(cn0) or not 0 < cn0 <= 100:
            omitted["invalid_cn0_or_code_lock"] += 1
            continue
        channel = None
        if system == 1 and signal in (0, 5):
            channel = observation.integer("frequency_channel") - 7
            if not -7 <= channel <= 6:
                omitted["unknown_glonass_channel"] += 1
                continue
        identity = tracking_signal(status, glonass_channel=channel)
        if identity is None or identity.frequency_hz is None:
            omitted["unknown_carrier"] += 1
            continue
        positions = geometry.get((system, prn), set())
        if len(positions) != 1:
            omitted["ambiguous_geometry" if positions else "missing_geometry"] += 1
            continue
        elevation, azimuth = next(iter(positions))
        lock = observation.get("lock_time")
        lock_seconds = float(lock) if isinstance(lock, (int, float)) else None
        if lock_seconds is not None and (
            not math.isfinite(lock_seconds) or lock_seconds < 0
        ):
            omitted["invalid_lock_time"] += 1
            continue
        l2c = bool(status & (1 << 26)) if system in (0, 5) and signal == 9 else False
        key = system, prn, signal, l2c
        sample = SatelliteSample(
            system,
            prn,
            signal,
            identity.frequency_hz,
            time_s,
            elevation,
            azimuth,
            cn0,
            lock_seconds,
            l2c,
        )
        previous = selected.get(key)
        if previous is None or sample.cn0 > previous.cn0:
            selected[key] = sample
        if previous is not None:
            omitted["duplicate_signal"] += 1
    return ReflectometryJoin(
        tuple(selected[key] for key in sorted(selected)), ambiguous, dict(omitted)
    )


def _bounds(
    min_elevation: float, max_elevation: float, min_height: float, max_height: float
) -> None:
    finite(min_elevation, max_elevation, min_height, max_height)
    if not 0 < min_elevation < max_elevation < 90:
        raise ValueError("elevation bounds must satisfy 0 < min < max < 90")
    if not 0 < min_height < max_height:
        raise ValueError("height bounds must satisfy 0 < min < max")


def _selected(samples: Sequence[SnrSample], low: float, high: float) -> list[SnrSample]:
    for sample in samples:
        finite(sample.elevation, sample.cn0)
        if not 0 < sample.elevation < 90 or not 0 < sample.cn0 <= 100:
            raise ValueError("samples need elevation in (0, 90) and C/N0 in (0, 100]")
    return [sample for sample in samples if low <= sample.elevation <= high]


def reflector_height_from_frequency(frequency: float, wavelength_m: float) -> float:
    finite(frequency, wavelength_m)
    if frequency <= 0 or wavelength_m <= 0:
        raise ValueError("frequency and wavelength must be positive")
    return wavelength_m * frequency / 2


def snr_periodogram(
    samples: Sequence[SnrSample],
    *,
    wavelength_m: float,
    min_elevation: float = MIN_ELEVATION_DEGREES,
    max_elevation: float = MAX_ELEVATION_DEGREES,
    min_height: float = MIN_HEIGHT_METRES,
    max_height: float = MAX_HEIGHT_METRES,
    order: int = DETREND_ORDER,
    oversample: int = FREQUENCY_OVERSAMPLE,
) -> Periodogram:
    """Scan linear C/N0 amplitude against sin(elevation), using bounded heights."""
    _bounds(min_elevation, max_elevation, min_height, max_height)
    finite(wavelength_m)
    if wavelength_m <= 0 or order < 0 or oversample < 1:
        raise ValueError(
            "wavelength and oversampling must be positive; order must be nonnegative"
        )
    selected = _selected(samples, min_elevation, max_elevation)
    if len(selected) < max(3, order + 2):
        raise ValueError("too few samples for detrending")
    sine = [math.sin(math.radians(sample.elevation)) for sample in selected]
    span = max(sine) - min(sine)
    if span <= 1e-8:
        raise ValueError("insufficient elevation variation")
    residual = detrend(sine, [10 ** (sample.cn0 / 20) for sample in selected], order)
    lowest, highest = 2 * min_height / wavelength_m, 2 * max_height / wavelength_m
    intervals = max(1, math.ceil((highest - lowest) * oversample * span))
    if intervals > 20_000:
        raise ValueError("height search exceeds 20000 bins; narrow the bounds")
    frequencies = tuple(
        lowest + (highest - lowest) * index / intervals
        for index in range(intervals + 1)
    )
    powers = tuple(lomb_scargle(sine, residual, frequencies))
    peak = max(range(len(powers)), key=powers.__getitem__)
    noise_amplitude = mean([math.sqrt(max(0.0, power)) for power in powers])
    return Periodogram(
        frequencies,
        powers,
        frequencies[peak],
        powers[peak],
        noise_amplitude**2,
        wavelength_m / (2 * span),
    )


def reflector_height(
    samples: Sequence[SnrSample],
    *,
    wavelength_m: float,
    min_elevation: float = MIN_ELEVATION_DEGREES,
    max_elevation: float = MAX_ELEVATION_DEGREES,
    min_height: float = MIN_HEIGHT_METRES,
    max_height: float = MAX_HEIGHT_METRES,
    order: int = DETREND_ORDER,
    threshold: float = PEAK_TO_NOISE_THRESHOLD,
) -> HeightEstimate | None:
    _bounds(min_elevation, max_elevation, min_height, max_height)
    finite(wavelength_m, threshold)
    if wavelength_m <= 0 or threshold <= 0:
        raise ValueError("wavelength and threshold must be positive")
    selected = _selected(samples, min_elevation, max_elevation)
    if len(selected) < max(MINIMUM_SAMPLES, order + 2):
        return None
    if (
        max(row.elevation for row in selected) - min(row.elevation for row in selected)
        < MINIMUM_ELEVATION_SPAN
    ):
        return None
    scan = snr_periodogram(
        selected,
        wavelength_m=wavelength_m,
        min_elevation=min_elevation,
        max_elevation=max_elevation,
        min_height=min_height,
        max_height=max_height,
        order=order,
    )
    if scan.peak_to_noise < threshold or scan.peak_frequency in (
        scan.frequencies[0],
        scan.frequencies[-1],
    ):
        return None
    return HeightEstimate(
        wavelength_m * scan.peak_frequency / 2, scan.peak_frequency, scan.peak_to_noise
    )


def _in_sector(azimuth: float, start: float, end: float) -> bool:
    return abs(end - start) == 360 or (azimuth - start) % 360 <= (end - start) % 360


def _make_arc(rows: Sequence[SatelliteSample], direction: int) -> Arc:
    first = rows[0]
    return Arc(
        first.system,
        first.prn,
        first.signal,
        first.frequency_hz,
        "rising" if direction > 0 else "setting" if direction < 0 else "stationary",
        tuple(rows),
        first.l2c_flag,
    )


def segment_arcs(
    samples: Sequence[SatelliteSample],
    *,
    max_gap_s: float = 15.0,
    min_elevation: float = MIN_ELEVATION_DEGREES,
    max_elevation: float = MAX_ELEVATION_DEGREES,
    azimuth_start: float = 0.0,
    azimuth_end: float = 360.0,
) -> tuple[Arc, ...]:
    """Split each carrier at gaps, lock resets, sector exits and direction changes."""
    _bounds(min_elevation, max_elevation, MIN_HEIGHT_METRES, MAX_HEIGHT_METRES)
    finite(max_gap_s, azimuth_start, azimuth_end)
    if (
        max_gap_s <= 0
        or not 0 <= azimuth_start <= 360
        or not 0 <= azimuth_end <= 360
        or azimuth_start == azimuth_end
    ):
        raise ValueError(
            "gap must be positive and azimuth sector must span (0, 360] degrees"
        )
    grouped: dict[tuple[int, int, int, float, bool], list[SatelliteSample]] = (
        defaultdict(list)
    )
    for sample in samples:
        finite(
            sample.frequency_hz,
            sample.time_s,
            sample.elevation,
            sample.azimuth,
            sample.cn0,
        )
        if sample.frequency_hz <= 0:
            raise ValueError("carrier frequency must be positive")
        grouped[
            sample.system,
            sample.prn,
            sample.signal,
            sample.frequency_hz,
            sample.l2c_flag,
        ].append(sample)
    arcs: list[Arc] = []
    for _, rows in sorted(grouped.items()):
        current: list[SatelliteSample] = []
        direction = 0
        for sample in rows:
            if current and sample.time_s <= current[-1].time_s:
                raise ValueError("epochs must increase strictly per satellite signal")
            if not min_elevation <= sample.elevation <= max_elevation or not _in_sector(
                sample.azimuth, azimuth_start, azimuth_end
            ):
                if current:
                    arcs.append(_make_arc(current, direction))
                current, direction = [], 0
                continue
            previous = current[-1] if current else None
            reset = previous is not None and (
                sample.time_s - previous.time_s > max_gap_s
                or (
                    sample.lock_seconds is not None
                    and previous.lock_seconds is not None
                    and sample.lock_seconds
                    < previous.lock_seconds + sample.time_s - previous.time_s - 0.1
                )
            )
            change = (
                0
                if previous is None
                else (sample.elevation > previous.elevation)
                - (sample.elevation < previous.elevation)
            )
            if reset or (change and direction and change != direction):
                if current:
                    arcs.append(_make_arc(current, direction))
                current, direction = [], 0
            current.append(sample)
            if change and not reset:
                direction = change
        if current:
            arcs.append(_make_arc(current, direction))
    return tuple(arcs)


def phase_feature(
    samples: Sequence[SnrSample], wavelength_m: float, height_m: float
) -> dict[str, float] | None:
    """Fit C/N0 interference phase jointly with its polynomial trend."""
    finite(wavelength_m, height_m)
    if wavelength_m <= 0 or height_m <= 0:
        raise ValueError("wavelength and reference height must be positive")
    if len(samples) < MINIMUM_SAMPLES:
        return None
    _selected(samples, 0, 90)
    if (
        max(row.elevation for row in samples) - min(row.elevation for row in samples)
        < MINIMUM_ELEVATION_SPAN
    ):
        return None
    sine = [math.sin(math.radians(row.elevation)) for row in samples]
    center, scale = mean(sine), max(sine) - min(sine)
    angle = [4 * math.pi * height_m * value / wavelength_m for value in sine]
    values = [10 ** (row.cn0 / 20) for row in samples]
    design = [
        [
            1.0,
            (value - center) / scale,
            ((value - center) / scale) ** 2,
            math.sin(phase),
            math.cos(phase),
        ]
        for value, phase in zip(sine, angle, strict=True)
    ]
    try:
        fit = least_squares(design, values, [1.0] * len(samples))
    except ValueError:
        return None
    residual = detrend(sine, values, DETREND_ORDER)
    total = math.fsum(value * value for value in residual)
    error = math.fsum(value * value for value in fit.residuals)
    a, b = fit.parameters[-2:]
    return {
        "phase_rad": math.atan2(b, a),
        "amplitude_relative": math.hypot(a, b),
        "fit_r2": max(0.0, min(1.0, 1 - error / total)) if total > 0 else 0.0,
        "residual_rms": math.sqrt(error / len(samples)),
        "reference_height_m": height_m,
    }


def assess_arc(
    arc: Arc,
    *,
    min_height: float = MIN_HEIGHT_METRES,
    max_height: float = MAX_HEIGHT_METRES,
    threshold: float = PEAK_TO_NOISE_THRESHOLD,
    min_samples: int = MINIMUM_SAMPLES,
    min_span: float = MINIMUM_ELEVATION_SPAN,
    min_duration: float = 60.0,
    min_amplitude: float = 0.0,
    min_fit_r2: float = 0.0,
) -> ArcResult:
    """Screen an arc before accepting a bounded spectral height."""
    _bounds(MIN_ELEVATION_DEGREES, MAX_ELEVATION_DEGREES, min_height, max_height)
    finite(
        threshold, min_span, min_duration, min_amplitude, min_fit_r2, arc.frequency_hz
    )
    if (
        arc.frequency_hz <= 0
        or threshold <= 0
        or min_samples < 3
        or min_span <= 0
        or min_duration < 0
        or min_amplitude < 0
        or not 0 <= min_fit_r2 <= 1
    ):
        raise ValueError("invalid arc quality thresholds")
    rows = arc.samples
    elevations = [row.elevation for row in rows]
    span = max(elevations) - min(elevations) if rows else 0.0
    duration = rows[-1].time_s - rows[0].time_s if rows else 0.0
    rejection: str | None = None
    scan = None
    fit = None
    estimate = None
    carrier = SPEED_OF_LIGHT / arc.frequency_hz
    if len(rows) < min_samples:
        rejection = "insufficient_samples"
    elif span < min_span:
        rejection = "insufficient_elevation_span"
    elif duration < min_duration:
        rejection = "insufficient_duration"
    elif any(
        abs(math.sin(math.radians(b.elevation)) - math.sin(math.radians(a.elevation)))
        > carrier / (4 * max_height)
        for a, b in pairwise(rows)
    ):
        rejection = "undersampled_for_max_height"
    else:
        scan = snr_periodogram(
            [SnrSample(row.elevation, row.cn0) for row in rows],
            wavelength_m=carrier,
            min_elevation=min(elevations),
            max_elevation=max(elevations),
            min_height=min_height,
            max_height=max_height,
        )
        height = carrier * scan.peak_frequency / 2
        fit = phase_feature(
            [SnrSample(row.elevation, row.cn0) for row in rows], carrier, height
        )
        if scan.peak_frequency in (scan.frequencies[0], scan.frequencies[-1]):
            rejection = "height_at_search_boundary"
        elif scan.peak_to_noise < threshold:
            rejection = "low_peak_to_noise"
        elif fit is None or fit["amplitude_relative"] < min_amplitude:
            rejection = "low_amplitude"
        elif fit["fit_r2"] < min_fit_r2:
            rejection = "poor_sinusoid_fit"
        else:
            estimate = HeightEstimate(height, scan.peak_frequency, scan.peak_to_noise)
    return ArcResult(
        arc.system,
        arc.prn,
        arc.signal,
        arc.frequency_hz,
        arc.direction,
        len(rows),
        duration,
        span,
        estimate,
        rejection,
        scan,
        fit,
    )


def reflection_footprint(arc: Arc, height_m: float) -> dict[str, object]:
    """Model the first Fresnel ellipse above a horizontal reflecting plane."""
    finite(height_m, arc.frequency_hz)
    if height_m <= 0 or arc.frequency_hz <= 0 or not arc.samples:
        raise ValueError(
            "footprint needs positive height, carrier frequency and samples"
        )
    carrier = SPEED_OF_LIGHT / arc.frequency_hz
    points: list[dict[str, float]] = []
    east_bounds: list[float] = []
    north_bounds: list[float] = []
    for sample in arc.samples:
        finite(sample.elevation, sample.azimuth)
        if not 0 < sample.elevation < 90:
            raise ValueError("footprint elevation must be in (0, 90)")
        elevation, azimuth = (
            math.radians(sample.elevation),
            math.radians(sample.azimuth),
        )
        sine, cosine = math.sin(elevation), math.cos(elevation)
        distance = height_m * cosine / sine
        center_distance = (height_m + carrier / (2 * sine)) * cosine / sine
        minor = math.sqrt(carrier * height_m / sine + (carrier / (2 * sine)) ** 2)
        major = minor / sine
        east, north = (
            center_distance * math.sin(azimuth),
            center_distance * math.cos(azimuth),
        )
        width = math.hypot(major * math.sin(azimuth), minor * math.cos(azimuth))
        length = math.hypot(major * math.cos(azimuth), minor * math.sin(azimuth))
        east_bounds.extend((east - width, east + width))
        north_bounds.extend((north - length, north + length))
        points.append(
            {
                "specular_east_m": distance * math.sin(azimuth),
                "specular_north_m": distance * math.cos(azimuth),
                "fresnel_center_east_m": east,
                "fresnel_center_north_m": north,
                "fresnel_semimajor_m": major,
                "fresnel_semiminor_m": minor,
            }
        )
    return {
        "reference_height_m": height_m,
        "start": points[0],
        "middle": points[len(points) // 2],
        "end": points[-1],
        "fresnel_bounds_m": {
            "east_min": min(east_bounds),
            "east_max": max(east_bounds),
            "north_min": min(north_bounds),
            "north_max": max(north_bounds),
        },
    }
