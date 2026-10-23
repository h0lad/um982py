"""Correlates tracking fields with independently labelled epochs."""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from um982py.experimental import TrackingField, tracking_fields, tracking_slots
from um982py.messages import Record
from um982py.stats import correlation, finite


@dataclass(frozen=True, slots=True)
class FieldHypothesis:
    """A statistical association retaining the original unverified field identity."""

    name: str
    offset: int
    storage: str
    pairs: int
    correlation: float | None


def written_fields(record: Record) -> tuple[TrackingField, ...]:
    """Omit slot values that the receiver did not write in this record."""
    slots = tracking_slots(record)
    return tuple(
        field
        for field in tracking_fields(record)
        if not (12 <= (index := int(field.name.removeprefix("field_"))) <= 29)
        or slots[index - 12].written
    )


def correlate_fields(
    frames: Sequence[tuple[float, tuple[TrackingField, ...]]],
    labels: Mapping[float, float],
    *,
    tolerance: float = 0.001,
) -> tuple[FieldHypothesis, ...]:
    """Join one-to-one labelled epochs and correlate without assigning units."""
    finite(tolerance, *labels.keys(), *labels.values())
    if tolerance < 0:
        raise ValueError("join tolerance must be nonnegative")
    if len({epoch for epoch, _ in frames}) != len(frames):
        raise ValueError(
            "duplicate tracking epochs require an explicit channel selector"
        )
    label_times = sorted(labels)
    used: set[float] = set()
    pairs: dict[tuple[str, int, str], tuple[list[float], list[float]]] = {}
    for epoch, fields in sorted(frames):
        finite(epoch)
        left = bisect_left(label_times, epoch - tolerance)
        right = bisect_right(label_times, epoch + tolerance)
        matches = [time for time in label_times[left:right] if time not in used]
        if len(matches) > 1:
            raise ValueError("ambiguous tracking label epoch join")
        if not matches:
            continue
        time = matches[0]
        used.add(time)
        for field in fields:
            if field.storage not in ("u", "i", "f", "d"):
                continue
            finite(float(field.value))
            x, y = pairs.setdefault((field.name, field.offset, field.storage), ([], []))
            x.append(float(field.value))
            y.append(labels[time])
    result = [
        FieldHypothesis(name, offset, storage, len(x), correlation(x, y))
        for (name, offset, storage), (x, y) in pairs.items()
    ]
    return tuple(
        sorted(
            result,
            key=lambda item: (
                -(abs(item.correlation) if item.correlation is not None else -1),
                item.offset,
            ),
        )
    )
