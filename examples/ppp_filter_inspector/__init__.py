"""Analyses internal PPP filter residuals, SSR satellite coverage and CPU load."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean

from um982py.commands import Log
from um982py.experimental import (
    PosDebugData,
    PppDebugData,
    PppDebugSatellite,
    ppp_debug_satellite,
)
from um982py.measurement import gps_epoch
from um982py.messages import BinaryMessage, Message
from um982py.messages.enums import SatelliteSystem
from um982py.messages.observations import TrackingStatus
from um982py.receiver_models import PerformanceStatus
from um982py.stats import norm, percentile, rms

__all__ = [
    "FrequencyResidualSummary",
    "PppFilterAnalysis",
    "analyse_ppp_filter",
    "match_ppp_range",
]


@dataclass(frozen=True, slots=True)
class FrequencyResidualSummary:
    """Summarises post-fit PPP filter residuals for one carrier frequency index."""

    frequency_index: int
    samples: int
    satellites: int
    rms_m: float
    max_abs_m: float
    p95_abs_m: float
    epochs_with_samples: int


@dataclass(frozen=True, slots=True)
class SatelliteResidualSummary:
    satellite: PppDebugSatellite
    frequency_index: int
    samples: int
    rms_m: float
    max_abs_m: float


@dataclass(frozen=True, slots=True)
class UpdateFailureSummary:
    system_index: int
    frequency_index: int
    epochs: int
    present_in_every_epoch: bool


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
    satellite_residuals: tuple[SatelliteResidualSummary, ...] = ()
    update_failures: tuple[UpdateFailureSummary, ...] = ()
    ambiguity_epochs: int = 0
    ambiguity_tokens: int = 0


def analyse_ppp_filter(
    ppp_records: Sequence[PppDebugData],
    pos_records: Sequence[PosDebugData] = (),
    performance: PerformanceStatus | None = None,
) -> PppFilterAnalysis:
    """Aggregate PPPDEBUGMSG residuals, FASTDEBUGMSG ADR lock ratios and CPU load."""
    residuals_by_frequency: dict[int, list[tuple[int, float]]] = defaultdict(list)
    epochs_by_frequency: dict[int, int] = defaultdict(int)
    residuals_by_satellite: dict[tuple[int, int], list[float]] = defaultdict(list)
    failure_epochs: Counter[tuple[int, int]] = Counter()
    position_steps: list[float] = []
    for record in ppp_records:
        failure_epochs.update(
            {
                (item.system_index, item.frequency_index)
                for item in record.update_failures
            }
        )
        if record.delta_position_m is not None:
            position_steps.append(norm(record.delta_position_m))
        for residual in record.residuals:
            residuals_by_satellite[residual.slot, residual.frequency_index].append(
                residual.residual_m
            )
            residuals_by_frequency[residual.frequency_index].append(
                (residual.slot, residual.residual_m)
            )
        for frequency in {residual.frequency_index for residual in record.residuals}:
            epochs_by_frequency[frequency] += 1
    frequency_summaries: list[FrequencyResidualSummary] = []
    for frequency_index, entries in sorted(residuals_by_frequency.items()):
        residual_values = [value for _, value in entries]
        magnitudes = [abs(value) for value in residual_values]
        frequency_summaries.append(
            FrequencyResidualSummary(
                frequency_index=frequency_index,
                samples=len(residual_values),
                satellites=len({slot for slot, _ in entries}),
                rms_m=rms(residual_values),
                max_abs_m=max(magnitudes),
                p95_abs_m=percentile(magnitudes, 0.95),
                epochs_with_samples=epochs_by_frequency[frequency_index],
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
        satellite_residuals=tuple(
            SatelliteResidualSummary(
                ppp_debug_satellite(slot),
                frequency,
                len(values),
                rms(values),
                max(map(abs, values)),
            )
            for (slot, frequency), values in sorted(residuals_by_satellite.items())
        ),
        update_failures=tuple(
            UpdateFailureSummary(system, frequency, count, count == len(ppp_records))
            for (system, frequency), count in sorted(failure_epochs.items())
        ),
        ambiguity_epochs=sum(
            bool(record.ambiguity_diagnostics) for record in ppp_records
        ),
        ambiguity_tokens=sum(
            len(record.ambiguity_diagnostics) for record in ppp_records
        ),
    )


@dataclass(frozen=True, slots=True)
class RangeSignalContext:
    tracking_status: int
    signal_code: int
    cn0_db_hz: float
    lock_seconds: float
    pseudorange_m: float
    carrier_phase_cycles: float
    doppler_hz: float


@dataclass(frozen=True, slots=True)
class PppRangeContext:
    week: int
    milliseconds: int
    satellite: PppDebugSatellite
    signals: tuple[RangeSignalContext, ...]


def match_ppp_range(
    ppp_records: Iterable[PppDebugData],
    messages: Iterable[Message],
    *,
    antenna: int = 1,
) -> tuple[PppRangeContext, ...]:
    """Join by exact time of week, antenna and verified satellite identity."""
    if antenna not in (1, 2):
        raise ValueError("Expected antenna 1 or 2")
    targets: dict[int, dict[tuple[int, int], PppDebugSatellite]] = defaultdict(dict)
    source = "PPPDEBUGMSG" if antenna == 1 else "PPPHDEBUGMSG"
    for record in ppp_records:
        if record.source != source:
            continue
        for satellite in (
            *record.iode_satellites,
            *(r.satellite for r in record.residuals),
        ):
            if satellite.system is not None and satellite.prn is not None:
                targets[record.milliseconds][
                    SatelliteSystem[satellite.system], satellite.prn
                ] = satellite

    if not targets:
        return ()
    log = Log.RANGE if antenna == 1 else Log.RANGEH
    matches: dict[int, tuple[int, list[PppRangeContext]]] = {}
    ambiguous: set[int] = set()
    for message in messages:
        if (
            not isinstance(message, BinaryMessage)
            or message.header.message_id != log.definition.message_id
        ):
            continue
        try:
            week, milliseconds = divmod(round(gps_epoch(message) * 1000), 604_800_000)
        except ValueError:
            continue
        if milliseconds not in targets or milliseconds in ambiguous:
            continue
        if milliseconds in matches:
            if matches[milliseconds][0] != week:
                ambiguous.add(milliseconds)
                del matches[milliseconds]
            continue
        signals: dict[PppDebugSatellite, list[RangeSignalContext]] = defaultdict(list)
        for row in log.decode(message).records("observations"):
            status = TrackingStatus(row.integer("tracking_status"))
            identity = targets[milliseconds].get((status.system, row.integer("prn")))
            if identity is not None:
                signals[identity].append(
                    RangeSignalContext(
                        status.raw,
                        status.signal,
                        row.real("cn0"),
                        row.real("lock_time"),
                        row.real("pseudorange"),
                        row.real("carrier_phase"),
                        row.real("doppler"),
                    )
                )
        matches[milliseconds] = (
            week,
            [
                PppRangeContext(week, milliseconds, satellite, tuple(rows))
                for satellite, rows in signals.items()
            ],
        )
    return tuple(context for _, contexts in matches.values() for context in contexts)
