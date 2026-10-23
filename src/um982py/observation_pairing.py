"""Match base and rover observation records without assuming phase alignment."""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.capture import record_epoch
from um982py.messages import Record


@dataclass(frozen=True, slots=True, order=True)
class ObservationIdentity:
    """Native signal identity, including the GLONASS frequency field."""

    system: int
    satellite: int
    signal: int
    signal_flag: bool
    frequency_channel: int


@dataclass(frozen=True, slots=True)
class ObservationPair:
    identity: ObservationIdentity
    base: Record
    rover: Record


@dataclass(frozen=True, slots=True)
class ObservationEpochPair:
    base_epoch: float
    rover_epoch: float
    pairs: tuple[ObservationPair, ...]
    base_only: int
    rover_only: int


def _observations(record: Record) -> dict[ObservationIdentity, Record]:
    result: dict[ObservationIdentity, Record] = {}
    for observation in record.records("observations"):
        status = observation.integer("ch_tr_status")
        key = ObservationIdentity(
            (status >> 16) & 7,
            observation.integer("prn_slot"),
            (status >> 21) & 31,
            bool(status & (1 << 26)),
            observation.integer("system_freq"),
        )
        if key in result:
            raise ValueError("duplicate native signal identity in an observation epoch")
        result[key] = observation
    return result


def pair_base_rover_observations(
    base: Sequence[Record], rover: Sequence[Record], *, tolerance: float = 0.0
) -> tuple[ObservationEpochPair, ...]:
    """Pair unique epochs and native signal identities without interpolation.

    Receiver epochs and signal identifiers need independent verification for
    scientific use. Multiple candidate epochs are rejected rather than guessed.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("epoch tolerance must be finite and nonnegative")
    if any(row.name != "OBSVBASE" for row in base) or any(
        row.name != "OBSVM" for row in rover
    ):
        raise ValueError("expected OBSVBASE base and OBSVM primary rover records")
    base_rows = sorted(
        ((record_epoch(row), row) for row in base), key=lambda row: row[0]
    )
    rover_rows = sorted(
        ((record_epoch(row), row) for row in rover), key=lambda row: row[0]
    )
    base_times = [epoch for epoch, _ in base_rows]
    rover_times = [epoch for epoch, _ in rover_rows]
    if len(set(base_times)) != len(base_times) or len(set(rover_times)) != len(
        rover_times
    ):
        raise ValueError("duplicate observation epochs are ambiguous")
    used: set[int] = set()
    result = []
    for epoch, row in base_rows:
        start = bisect_left(rover_times, epoch - tolerance)
        end = bisect_right(rover_times, epoch + tolerance)
        candidates = list(range(start, end))
        if len(candidates) > 1:
            raise ValueError("multiple rover epochs fall inside the matching window")
        if not candidates:
            continue
        index = candidates[0]
        if index in used:
            raise ValueError("multiple base epochs match the same rover epoch")
        used.add(index)
        rover_epoch, rover_row = rover_rows[index]
        left, right = _observations(row), _observations(rover_row)
        common = left.keys() & right.keys()
        result.append(
            ObservationEpochPair(
                epoch,
                rover_epoch,
                tuple(
                    ObservationPair(key, left[key], right[key])
                    for key in sorted(common)
                ),
                len(left.keys() - right.keys()),
                len(right.keys() - left.keys()),
            )
        )
    return tuple(result)
