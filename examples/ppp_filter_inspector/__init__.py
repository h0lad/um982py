"""Analyses internal PPP filter residuals, SSR satellite coverage and CPU load."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from um982py.experimental import PosDebugData, PppDebugData
from um982py.receiver_models import PerformanceStatus
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
    residuals_by_frequency: dict[int, list[tuple[int, float]]] = defaultdict(list)
    position_steps: list[float] = []
    for record in ppp_records:
        if record.delta_position_m is not None:
            position_steps.append(norm(record.delta_position_m))
        for residual in record.residuals:
            residuals_by_frequency[residual.frequency_index].append(
                (residual.slot, residual.residual_m)
            )
    frequency_summaries: list[FrequencyResidualSummary] = []
    for frequency_index, entries in sorted(residuals_by_frequency.items()):
        residual_values = [value for _, value in entries]
        frequency_summaries.append(
            FrequencyResidualSummary(
                frequency_index=frequency_index,
                samples=len(residual_values),
                satellites=len({slot for slot, _ in entries}),
                rms_m=rms(residual_values),
                max_abs_m=max(abs(value) for value in residual_values),
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
            (record.corrected_counts["GPS"] for record in ppp_records), default=None
        ),
        max_corrected_galileo=max(
            (record.corrected_counts["GALILEO"] for record in ppp_records), default=None
        ),
        max_corrected_beidou_b2b=max(
            (record.corrected_counts["BEIDOU_B2B"] for record in ppp_records),
            default=None,
        ),
        max_corrected_beidou=max(
            (record.corrected_counts["BEIDOU"] for record in ppp_records), default=None
        ),
        max_processed_satellites=max(
            (
                record.processed_satellites
                for record in ppp_records
                if record.processed_satellites is not None
            ),
            default=None,
        ),
        step_rms_m=rms(position_steps) if position_steps else None,
        frequency_residuals=tuple(frequency_summaries),
        mean_adr_lock_ratio=fmean(adr_ratios) if adr_ratios else None,
        cpu_load_percent=(
            performance.cpu_load_percent if performance is not None else None
        ),
    )
