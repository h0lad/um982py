"""Declared receiver and acquisition identity for observation records."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py.messages.record import Record

__all__ = ["ObservationSource"]

_ANTENNAS = {
    "RANGE": 1,
    "RANGEH": 2,
    "OBSVM": 1,
    "OBSVH": 2,
    "OBSVMCMP": 1,
    "OBSVHCMP": 2,
}


@dataclass(frozen=True, slots=True)
class ObservationSource:
    """Identity declared by the acquisition application, not decoded from wire data.

    ``receiver_id`` is a known serial number or application label, or None when
    unknown. ``session_id`` identifies one continuous acquisition, so use a
    new ID after reconnects, reboots or antenna changes. IDs do not prove
    phase continuity.
    """

    receiver_id: str | None
    session_id: str
    antenna: int

    def __post_init__(self) -> None:
        for name, value in (
            ("receiver_id", self.receiver_id),
            ("session_id", self.session_id),
        ):
            if name == "receiver_id" and value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if type(self.antenna) is not int or self.antenna not in (1, 2):
            raise ValueError("antenna must be 1 or 2")


def _observation_source(
    records: Sequence["Record"], declared: ObservationSource | None = None
) -> ObservationSource | None:
    if declared is not None and not isinstance(declared, ObservationSource):
        raise TypeError("source must be an ObservationSource")
    if any(
        record.source is not None and not isinstance(record.source, ObservationSource)
        for record in records
    ):
        raise TypeError("record source must be an ObservationSource")
    sources = {record.source for record in records}
    known = sources - {None}
    if len(known) > 1 or (declared is not None and known and known != {declared}):
        raise ValueError(
            "observation records have different receiver, session or antenna sources"
        )
    if known and None in sources and declared is None:
        raise ValueError("cannot mix observations with known and unknown sources")
    source = declared if declared is not None else next(iter(known), None)
    if source is not None:
        for record in records:
            antenna = _ANTENNAS.get(record.name)
            if antenna is not None and source.antenna != antenna:
                raise ValueError(
                    "observation source antenna disagrees with the wire log"
                )
    return source
