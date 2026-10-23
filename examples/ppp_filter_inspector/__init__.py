"""Analyses internal PPP filter residuals, SSR satellite coverage and CPU load."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from um982py.experimental import (
    PerformanceStatus,
    PosDebugData,
    PppDebugData,
)
from um982py.stats import norm, rms

__all__ = [
    "FrequencyResidualSummary",
    "PppFilterAnalysis",
    "analyse_ppp_filter",
]


@dataclass(frozen=True, slots=True)
class FrequencyResidualSummary:
    """Summarises post-fit PPP filter residuals for one carrier frequency index."""

    frequency_index: int
    samples: int
    satellites: int
    rms_m: float
    max_abs_m: float


@dataclass(frozen=True, slots=True)
class PppFilterAnalysis:
    """Summarises internal PPP filter SSR coverage, carrier residuals and CPU load."""

    epochs: int
    max_corrected_gps: int | None
    max_corrected_galileo: int | None
    max_corrected_beidou_b2b: int | None
    max_corrected_beidou: int | None
    max_processed_satellites: int | None
    step_rms_m: float | None
    frequency_residuals: tuple[FrequencyResidualSummary, ...]
    mean_adr_lock_ratio: float | None
    cpu_load_percent: float | None


def analyse_ppp_filter(
    ppp_records: Sequence[PppDebugData],
    pos_records: Sequence[PosDebugData] = (),
    performance: PerformanceStatus | None = None,
) -> PppFilterAnalysis:
    """Aggregate PPPDEBUGMSG residuals, FASTDEBUGMSG ADR lock ratios and CPU load."""
    by_freq: dict[int, list[tuple[int, float]]] = defaultdict(list)
    steps: list[float] = []
    for record in ppp_records:
        if record.delta_position_m is not None:
            steps.append(norm(record.delta_position_m))
        for res in record.residuals:
            by_freq[res.frequency_index].append((res.slot, res.residual_m))
    freq_summaries: list[FrequencyResidualSummary] = []
    for freq_idx, entries in sorted(by_freq.items()):
        values = [val for _, val in entries]
        freq_summaries.append(
            FrequencyResidualSummary(
                frequency_index=freq_idx,
                samples=len(values),
                satellites=len({slot for slot, _ in entries}),
                rms_m=rms(values),
                max_abs_m=max(abs(val) for val in values),
            )
        )
    adr_ratios = [
        pos.adr_locked / pos.adr_total
        for pos in pos_records
        if pos.adr_locked is not None
        and pos.adr_total is not None
        and pos.adr_total > 0
    ]
    return PppFilterAnalysis(
        epochs=len(ppp_records),
        max_corrected_gps=max(
            (r.corrected_counts["GPS"] for r in ppp_records), default=None
        ),
        max_corrected_galileo=max(
            (r.corrected_counts["GALILEO"] for r in ppp_records), default=None
        ),
        max_corrected_beidou_b2b=max(
            (r.corrected_counts["BEIDOU_B2B"] for r in ppp_records), default=None
        ),
        max_corrected_beidou=max(
            (r.corrected_counts["BEIDOU"] for r in ppp_records), default=None
        ),
        max_processed_satellites=max(
            (
                r.processed_satellites
                for r in ppp_records
                if r.processed_satellites is not None
            ),
            default=None,
        ),
        step_rms_m=rms(steps) if steps else None,
        frequency_residuals=tuple(freq_summaries),
        mean_adr_lock_ratio=fmean(adr_ratios) if adr_ratios else None,
        cpu_load_percent=(
            performance.cpu_load_percent if performance is not None else None
        ),
    )
