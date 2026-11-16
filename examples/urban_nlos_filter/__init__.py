"""Urban NLOS classification from SATSINFO sky-track and signal strength.

Satellites in an urban canyon are often received via reflections or diffraction.
A simple receiver-only classifier uses elevation angle and carrier-to-noise
density: low-elevation and low-C/N0 signals are more likely to be non-line-of-sight.
The score is intentionally conservative; it flags candidates rather than proving
NLOS reception.

Reference
---------
Groves, P. D., & Jiang, Z. (2013). Height Aiding, C/N0 Weighting and Consistency
Checking for GNSS NLOS and Multipath Mitigation in Urban Areas. The Journal of
Navigation, 66(6), 653-669. doi:10.1017/S0373463313000169
"""

from __future__ import annotations

from dataclasses import dataclass

from um982py.messages import Record
from um982py.satellites import Satellite, satellites_from_record


@dataclass(frozen=True, slots=True)
class NlosCandidate:
    """One satellite classified as likely LOS/NLOS."""

    prn: int
    constellation: str | None
    elevation_deg: int
    azimuth_deg: int
    snr_db_hz: int
    score: float
    label: str


def nlos_score(elevation_deg: float, snr_db_hz: float) -> float:
    """Return a 0..1 NLOS likelihood score.

    Combines an elevation factor (lower elevation -> higher score) and a C/N0
    factor (lower C/N0 -> higher score).  Both factors are normalised so that
    the score reaches 0.5 at typical urban thresholds (~30 deg elevation,
    ~35 dB-Hz C/N0).
    """
    elevation = max(0.0, min(90.0, float(elevation_deg)))
    snr = max(0.0, min(60.0, float(snr_db_hz)))
    elevation_factor = 1.0 - (elevation / 90.0) ** 0.5
    snr_factor = 1.0 - (snr / 50.0) ** 1.5
    return float(
        max(0.0, min(1.0, 0.5 * elevation_factor + 0.5 * max(0.0, snr_factor)))
    )


def classify_satellite(
    satellite: Satellite,
    low_threshold: float = 0.45,
    high_threshold: float = 0.75,
) -> list[NlosCandidate]:
    """Classify each SATSINFO signal of a satellite."""
    results: list[NlosCandidate] = []
    for signal in satellite.signals:
        score = nlos_score(satellite.elevation_deg, signal.snr)
        if score >= high_threshold:
            label = "NLOS"
        elif score >= low_threshold:
            label = "unsure"
        else:
            label = "LOS"
        results.append(
            NlosCandidate(
                prn=satellite.prn,
                constellation=signal.constellation or satellite.constellation,
                elevation_deg=satellite.elevation_deg,
                azimuth_deg=satellite.azimuth_deg,
                snr_db_hz=signal.snr,
                score=score,
                label=label,
            )
        )
    return results


def classify_record(
    record: Record,
    *,
    low_threshold: float = 0.45,
    high_threshold: float = 0.75,
) -> tuple[float, list[NlosCandidate]]:
    """Classify all tracked satellites in one SATSINFO epoch.

    Returns the mean NLOS score across all signals and the per-signal list.
    """
    satellites = satellites_from_record(record)
    candidates: list[NlosCandidate] = []
    for sat in satellites:
        candidates.extend(classify_satellite(sat, low_threshold, high_threshold))
    mean_score = (
        sum(c.score for c in candidates) / len(candidates) if candidates else 0.0
    )
    return mean_score, candidates
