"""Solves receiver velocity and clock drift from corrected Doppler."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

SPECTRAL_FLOOR_HZ = 1e-6


@dataclass(frozen=True, slots=True)
class WaveParameters:
    """First-order sea-state parameters of a vertical velocity series."""

    significant_height_m: float
    peak_period_s: float
    mean_period_s: float
    vertical_rms_m_s: float
    sample_count: int


def wave_spectrum(
    velocity: Sequence[float], interval_seconds: float
) -> tuple[tuple[float, float], ...]:
    """Displacement spectral density of a detrended vertical velocity series.

    The vertical velocity of a harmonic wave scales the displacement by its
    angular frequency, so the velocity periodogram is divided by ``omega^2``
    to recover the displacement density.  The mean current is removed because
    a constant vertical velocity carries no wave energy.
    """
    if len(velocity) < 8:
        raise ValueError("at least eight samples are required")
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("interval must be finite and positive")
    if not all(math.isfinite(value) for value in velocity):
        raise ValueError("velocity samples must be finite")
    count = len(velocity)
    average = math.fsum(velocity) / count
    window = [
        0.5 - 0.5 * math.cos(2.0 * math.pi * index / (count - 1))
        for index in range(count)
    ]
    window_energy = math.fsum(value * value for value in window)
    spectrum = []
    for bin_index in range(1, count // 2 + 1):
        frequency = bin_index / (count * interval_seconds)
        if frequency <= SPECTRAL_FLOOR_HZ:
            continue
        real = math.fsum(
            (velocity[index] - average)
            * window[index]
            * math.cos(2.0 * math.pi * bin_index * index / count)
            for index in range(count)
        )
        imaginary = math.fsum(
            (velocity[index] - average)
            * window[index]
            * -math.sin(2.0 * math.pi * bin_index * index / count)
            for index in range(count)
        )
        # The Nyquist bin has no distinct negative-frequency counterpart.
        one_sided_factor = 1.0 if count % 2 == 0 and bin_index == count // 2 else 2.0
        velocity_density = (
            one_sided_factor
            * (real * real + imaginary * imaginary)
            * interval_seconds
            / window_energy
        )
        omega = 2.0 * math.pi * frequency
        spectrum.append((frequency, velocity_density / (omega * omega)))
    return tuple(spectrum)


def wave_parameters(
    velocity: Sequence[float], interval_seconds: float
) -> WaveParameters:
    """Significant height and periods from the spectral moments of heave.

    Significant height is four times the square root of the displacement
    variance ``m0``. The mean period is ``sqrt(m0 / m2)``, and the peak period
    is the inverse of the strongest spectral bin. This is a first-order
    estimate that ignores the directional spreading of a real sea.
    """
    spectrum = wave_spectrum(velocity, interval_seconds)
    if not spectrum:
        raise ValueError("series is too short for a spectral estimate")
    bandwidth = spectrum[0][0]
    m0 = math.fsum(density * bandwidth for _, density in spectrum)
    m2 = math.fsum(
        frequency * frequency * density * bandwidth for frequency, density in spectrum
    )
    peak_frequency, _ = max(spectrum, key=lambda row: row[1])
    rms = math.sqrt(math.fsum(value * value for value in velocity) / len(velocity))
    return WaveParameters(
        significant_height_m=4.0 * math.sqrt(m0),
        peak_period_s=1.0 / peak_frequency,
        mean_period_s=math.sqrt(m0 / m2) if m2 > 0 else math.nan,
        vertical_rms_m_s=rms,
        sample_count=len(velocity),
    )
