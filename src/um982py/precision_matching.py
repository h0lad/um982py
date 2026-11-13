"""Conservative matching of GGA fixes and GST precision records."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import TYPE_CHECKING

from um982py.errors import ProtocolError
from um982py.messages.navigation import Fix
from um982py.messages.record import Record
from um982py.precision import PositionPrecision, utc_seconds

if TYPE_CHECKING:
    from um982py.streaming import StreamEvent


@dataclass(frozen=True, slots=True)
class PrecisionMatches:
    """Fixes and counts from a conservative batch precision match."""

    fixes: tuple[Fix, ...]
    statistics: int
    matched: int
    ambiguous: int
    rejected: int


def match_precision(
    fixes: Sequence[Record], statistics: Sequence[Record], *, max_records: int = 10000
) -> PrecisionMatches:
    """Match a bounded batch known by the caller to be from one session.

    Records carry neither a date nor arrival times. Repeated time-of-day and
    antenna keys are rejected as ambiguous. For live data, use
    ``match_stream_precision`` to also check stream identity and completion time.
    """
    if type(max_records) is not int or max_records < 1:
        raise ValueError("max_records must be a positive integer")
    if len(fixes) + len(statistics) > max_records:
        raise ValueError("precision batch exceeds max_records")
    return _match(
        [(record, "session", None) for record in fixes],
        [(record, "session", None) for record in statistics],
        max_records=max_records,
        max_separation_s=None,
    )


def match_stream_precision(
    fixes: Sequence[StreamEvent],
    statistics: Sequence[StreamEvent],
    *,
    max_separation_s: float = 2.0,
    max_records: int = 10000,
) -> PrecisionMatches:
    """Match events from the same session and nearby host completion times.

    Completion is when the full frame was decoded, not the receiver epoch or
    the first byte's arrival. Monitor stream drops and session health too.
    Duplicate keys within the supplied batch are treated as ambiguous.
    """
    from um982py.messages.decode import decode_log

    if (
        isinstance(max_separation_s, bool)
        or not isfinite(max_separation_s)
        or not 0 <= max_separation_s < 43200
    ):
        raise ValueError("max_separation_s must be finite and less than 12 hours")
    if type(max_records) is not int or max_records < 1:
        raise ValueError("max_records must be a positive integer")
    if len(fixes) + len(statistics) > max_records:
        raise ValueError("precision batch exceeds max_records")

    def decode(events: Sequence[StreamEvent]) -> list[tuple[Record, str, float]]:
        return [
            (decode_log(event.message), event.session_id, event.received_monotonic)
            for event in events
        ]

    return _match(
        decode(fixes),
        decode(statistics),
        max_records=max_records,
        max_separation_s=max_separation_s,
    )


def _match(
    fixes: Sequence[tuple[Record, str, float | None]],
    statistics: Sequence[tuple[Record, str, float | None]],
    *,
    max_records: int,
    max_separation_s: float | None,
) -> PrecisionMatches:
    if type(max_records) is not int or max_records < 1:
        raise ValueError("max_records must be a positive integer")
    if len(fixes) + len(statistics) > max_records:
        raise ValueError("precision batch exceeds max_records")
    Key = tuple[str, int, Decimal]
    parsed: list[tuple[Fix, Key, float | None]] = []
    rejected = 0
    for record, session, arrival in fixes:
        try:
            fix = Fix.from_record(record)
            if not fix.valid or fix.antenna is None or not session:
                raise ValueError("fix identity unavailable")
            parsed.append((fix, (session, fix.antenna, utc_seconds(fix.utc)), arrival))
        except (ProtocolError, ValueError):
            rejected += 1
    candidates: dict[Key, list[tuple[Record, float | None]]] = defaultdict(list)
    for record, session, arrival in statistics:
        try:
            precision = PositionPrecision.from_gst(record)
            if precision.antenna is None or precision.utc is None or not session:
                raise ValueError("GST identity unavailable")
            candidates[(session, precision.antenna, utc_seconds(precision.utc))].append(
                (record, arrival)
            )
        except (ProtocolError, ValueError):
            rejected += 1
    counts = Counter(key for _, key, _ in parsed)
    output = []
    matched = ambiguous = 0
    for fix, key, arrival in parsed:
        available = candidates.get(key, [])
        if counts[key] == 1 and len(available) == 1:
            record, other_arrival = available[0]
            near = max_separation_s is None or (
                arrival is not None
                and other_arrival is not None
                and isfinite(arrival)
                and isfinite(other_arrival)
                and abs(arrival - other_arrival) <= max_separation_s
            )
            if near:
                fix = fix.with_gst(record)
                matched += fix.precision is not None
        elif available:
            ambiguous += 1
        output.append(fix)
    return PrecisionMatches(
        tuple(output), len(statistics), matched, ambiguous, rejected
    )
