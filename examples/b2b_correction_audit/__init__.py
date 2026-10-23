"""Checks PPP-B2b and Galileo HAS correction age and issue coherence."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from um982py.capture import record_epoch
from um982py.corrections import CorrectionCheck, CorrectionEvent, audit_corrections
from um982py.messages import Record
from um982py.messages.enums import PositionType, SolutionStatus

__all__ = [
    "CorrectionCheck",
    "CorrectionEvent",
    "NavigationAlignment",
    "ServiceAudit",
    "align_navigation",
    "audit_corrections",
    "chronological",
    "service_census",
    "service_of",
]


@dataclass(frozen=True, slots=True)
class ServiceAudit:
    """Coherence census of one satellite-delivered correction service."""

    service: str
    blocks: int
    flagged: int
    status: str

    @property
    def clean(self) -> bool:
        """True only when the service delivered blocks and none was flagged."""
        return self.blocks > 0 and self.flagged == 0


@dataclass(frozen=True, slots=True)
class NavigationAlignment:
    gps_epoch: float
    position_type: str
    solution_status: str
    recent_b2b_blocks: int
    recent_b2b_clean_blocks: int
    recent_has_blocks: int
    recent_has_clean_blocks: int
    correction_application_verified: bool


def _label(value: object, kind: type[PositionType] | type[SolutionStatus]) -> str:
    try:
        return kind(int(str(value))).name
    except (ValueError, TypeError):
        return str(value)


def align_navigation(
    records: Sequence[Record],
    b2b_checks: Sequence[CorrectionCheck],
    has_checks: Sequence[Mapping[str, object]],
    *,
    window_seconds: float = 60.0,
) -> tuple[NavigationAlignment, ...]:
    if not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("alignment window must be finite and positive")
    result = []
    for record in records:
        epoch = record_epoch(record)
        b2b = [
            item for item in b2b_checks if 0 <= epoch - item.received <= window_seconds
        ]
        has = [
            item
            for item in has_checks
            if isinstance((received := item.get("received_gps_seconds")), (float, int))
            and 0 <= epoch - received <= window_seconds
        ]
        result.append(
            NavigationAlignment(
                epoch,
                _label(record["pos_type"], PositionType),
                _label(record["sol_status"], SolutionStatus),
                len(b2b),
                sum(not item.flags for item in b2b),
                len(has),
                sum(not item.get("flags") for item in has),
                False,
            )
        )
    return tuple(result)


def service_of(name: str) -> str:
    """Name the correction service that publishes a decoded log ``name``."""
    if name.startswith("PPPB2BINFO"):
        return "b2b"
    if name.startswith("E6"):
        return "has"
    raise ValueError("name is not a satellite correction record")


def service_census(
    b2b_checks: Sequence[CorrectionCheck],
    has_checks: Sequence[Mapping[str, object]],
) -> tuple[ServiceAudit, ServiceAudit]:
    """Summarise both free correction services from their computed checks.

    The two services use different block grammars, so the census only reports
    delivery and flag counts.  It makes no statement about which service is
    more accurate, and an empty service is reported as ``no_blocks`` rather
    than as clean.
    """
    has_flags = [check.get("flags") for check in has_checks]
    for flags in has_flags:
        if not isinstance(flags, Sequence) or isinstance(flags, (str, bytes)):
            raise ValueError("HAS checks must carry a flag sequence")
    return (
        ServiceAudit(
            "b2b",
            len(b2b_checks),
            sum(bool(check.flags) for check in b2b_checks),
            "no_blocks" if not b2b_checks else "checked",
        ),
        ServiceAudit(
            "has",
            len(has_checks),
            sum(bool(flags) for flags in has_flags),
            "no_blocks" if not has_checks else "checked",
        ),
    )


def chronological(records: Sequence[Record]) -> tuple[Record, ...]:
    """Order correction records by their receiver epoch, not by log name."""
    return tuple(sorted(records, key=record_epoch))
