"""Audits baseband counter transitions and tracking-slot statistics."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from um982py.experimental import BasebandNotice, tracking_slots
from um982py.messages import Record


@dataclass(frozen=True, slots=True)
class CounterTransition:
    """A native tag difference with no assumed time base or wrap modulus."""

    header_index: int
    before: int
    after: int
    difference: int
    classification: str


@dataclass(frozen=True, slots=True)
class SlotSummary:
    """Capture-wide slot values including only finite channel-written samples."""

    slot: int
    bank: int
    bank_slot: int
    frames: int
    written_frames: int
    unwritten_frames: int
    nonfinite_written_frames: int
    minimum_native: float | None
    median_native: float | None
    maximum_native: float | None


@dataclass(frozen=True, slots=True)
class BasebandAudit:
    """Observed notice sequence and tracking coverage without physical attribution."""

    notice_counts: tuple[tuple[str, int], ...]
    native_tag_counts: tuple[int, ...]
    transitions: tuple[CounterTransition, ...]
    slot_summaries: tuple[SlotSummary, ...]


def audit_baseband(
    notices: Sequence[BasebandNotice], records: Sequence[Record]
) -> BasebandAudit:
    """Audit native counter order and exclude unwritten slot memory from statistics."""
    tags = tuple(
        notice.decode().integer("tag_count")
        for notice in notices
        if notice.name == "BBNOTICE"
    )
    transitions = tuple(
        CounterTransition(
            index,
            before,
            after,
            after - before,
            "duplicate"
            if after == before
            else "backward_or_wrap"
            if after < before
            else "unit_increment"
            if after == before + 1
            else "forward_jump",
        )
        for index, (before, after) in enumerate(pairwise(tags), start=1)
    )
    values: list[list[float]] = [[] for _ in range(18)]
    written, invalid = [0] * 18, [0] * 18
    for record in records:
        for slot in tracking_slots(record):
            if slot.written:
                written[slot.slot] += 1
                if math.isfinite(slot.native_value):
                    values[slot.slot].append(slot.native_value)
                else:
                    invalid[slot.slot] += 1
    summaries = tuple(
        SlotSummary(
            index,
            index // 9,
            index % 9,
            len(records),
            written[index],
            len(records) - written[index],
            invalid[index],
            min(value) if value else None,
            median(value) if value else None,
            max(value) if value else None,
        )
        for index, value in enumerate(values)
    )
    return BasebandAudit(
        tuple(sorted(Counter(notice.name for notice in notices).items())),
        tags,
        transitions,
        summaries,
    )
