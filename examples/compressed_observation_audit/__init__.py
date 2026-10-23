"""Audit RANGECMP agreement against full RANGE observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from um982py.experimental import CompressedObservation
from um982py.messages import Record

__all__ = [
    "AuditSummary",
    "EpochAgreement",
    "agree_epoch",
    "summarise_epochs",
]


@dataclass(frozen=True, slots=True)
class EpochAgreement:
    """Per-epoch match counts and worst-case reconstruction residuals."""

    matched: int
    unmatched: int
    worst_pseudorange_m: float
    worst_doppler_hz: float
    worst_phase_cycles: float | None
    saturated_cn0: int
    range_bytes: int
    compressed_bytes: int


@dataclass(frozen=True, slots=True)
class AuditSummary:
    """Whole-capture match counts, worst residuals and wire-size ratio."""

    epochs: int
    matched: int
    unmatched: int
    worst_pseudorange_m: float
    worst_doppler_hz: float
    worst_phase_cycles: float | None
    saturated_cn0: int
    range_bytes: int
    compressed_bytes: int
    ratio: float


def agree_epoch(
    range_lookup: Mapping[int, Record],
    compressed: Sequence[CompressedObservation],
    *,
    range_bytes: int,
    compressed_bytes: int,
) -> EpochAgreement:
    """Match compressed observations by tracking status and score residuals."""
    worst_pseudorange = 0.0
    worst_doppler = 0.0
    worst_phase: float | None = None
    matched = 0
    saturated = 0
    for observation in compressed:
        reference = range_lookup.get(observation.tracking_status)
        if reference is None:
            continue
        matched += 1
        worst_pseudorange = max(
            worst_pseudorange,
            abs(observation.pseudorange_m - reference.real("pseudorange")),
        )
        worst_doppler = max(
            worst_doppler, abs(observation.doppler_hz - reference.real("doppler"))
        )
        if observation.carrier_phase_cycles is not None:
            residual = abs(
                observation.carrier_phase_cycles - reference.real("carrier_phase")
            )
            worst_phase = (
                residual if worst_phase is None else max(worst_phase, residual)
            )
        if observation.cn0_saturated:
            saturated += 1
    return EpochAgreement(
        matched=matched,
        unmatched=len(compressed) - matched,
        worst_pseudorange_m=worst_pseudorange,
        worst_doppler_hz=worst_doppler,
        worst_phase_cycles=worst_phase,
        saturated_cn0=saturated,
        range_bytes=range_bytes,
        compressed_bytes=compressed_bytes,
    )


def summarise_epochs(agreements: Iterable[EpochAgreement]) -> AuditSummary:
    """Combine per-epoch agreements into whole-capture totals."""
    rows = tuple(agreements)
    phases = [
        agreement.worst_phase_cycles
        for agreement in rows
        if agreement.worst_phase_cycles is not None
    ]
    range_bytes = sum(agreement.range_bytes for agreement in rows)
    compressed_bytes = sum(agreement.compressed_bytes for agreement in rows)
    return AuditSummary(
        epochs=len(rows),
        matched=sum(agreement.matched for agreement in rows),
        unmatched=sum(agreement.unmatched for agreement in rows),
        worst_pseudorange_m=max(
            (agreement.worst_pseudorange_m for agreement in rows), default=0.0
        ),
        worst_doppler_hz=max(
            (agreement.worst_doppler_hz for agreement in rows), default=0.0
        ),
        worst_phase_cycles=max(phases) if phases else None,
        saturated_cn0=sum(agreement.saturated_cn0 for agreement in rows),
        range_bytes=range_bytes,
        compressed_bytes=compressed_bytes,
        ratio=compressed_bytes / range_bytes if range_bytes else 0.0,
    )
