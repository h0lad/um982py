"""Receiver-reported observation continuity, without inferring cycle slips."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.rinex import _observation


@dataclass(frozen=True, slots=True)
class LockReset:
    epoch_gps_seconds: float
    system_code: int
    satellite_id: int
    signal_code: int
    l2c_flag: bool
    previous_lock_seconds: float
    lock_seconds: float


@dataclass(frozen=True, slots=True)
class ObservationQuality:
    epochs: int
    missing_code_flags: int
    missing_phase_flags: int
    duplicate_signals: int
    gaps: tuple[tuple[float, float], ...]
    lock_resets: tuple[LockReset, ...]


def audit_observations(
    records: Sequence[Record], *, expected_interval: float | None = None
) -> ObservationQuality:
    """Audit a log in GPST order, using the supplied cadence to identify gaps.

    Resets report decreases in receiver lock time, not independently verified
    cycle slips. Gaps are pairs of observed epoch times, not a count of missing
    measurements. Invalid phases are excluded from lock-time comparisons.
    """
    names = {record.name for record in records}
    if (
        not records
        or len(names) != 1
        or not names <= {"RANGE", "RANGEH", "OBSVM", "OBSVH", "OBSVBASE"}
    ):
        raise ValueError("one uncompressed observation log is required")
    if expected_interval is not None and (
        not math.isfinite(expected_interval) or expected_interval <= 0
    ):
        raise ValueError("expected interval must be finite and positive")
    previous_epoch = None
    locks: dict[tuple[int, int, int, bool], float] = {}
    gaps = []
    resets = []
    missing_code = missing_phase = duplicates = 0
    for record in records:
        if record.message is None:
            raise ValueError("observation record has no receiver timestamp")
        epoch = gps_epoch(record.message)
        if previous_epoch is not None:
            elapsed = epoch - previous_epoch
            if elapsed <= 0:
                raise ValueError("observation epochs must increase strictly")
            if expected_interval is not None and elapsed > expected_interval + max(
                1e-3, expected_interval * 0.01
            ):
                gaps.append((previous_epoch, epoch))
        previous_epoch = epoch
        seen: set[tuple[int, int, int, bool]] = set()
        for native in record.records("observations"):
            row = _observation(native, record.name)
            status = row.integer("tracking_status")
            missing_code += not bool(status & 0x1000)
            missing_phase += not bool(status & 0x0400)
            key = (
                (status >> 16) & 7,
                row.integer("prn"),
                (status >> 21) & 31,
                bool(status & (1 << 26)),
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            if not status & 0x0400:
                continue
            lock = row.real("lock_time")
            if not math.isfinite(lock) or lock < 0:
                continue
            if key in locks and lock < locks[key]:
                resets.append(LockReset(epoch, *key, locks[key], lock))
            locks[key] = lock
    return ObservationQuality(
        len(records),
        missing_code,
        missing_phase,
        duplicates,
        tuple(gaps),
        tuple(resets),
    )
