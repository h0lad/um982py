"""Inspects captured baseband containers, inner messages and notices."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from um982py.errors import ProtocolError
from um982py.experimental import (
    BASEBAND_MESSAGE_CATALOGUE,
    BasebandHeader,
    BasebandMessageFamily,
    BasebandStream,
    RawBasebandPacket,
    decode_message_payload,
    scan_notices,
)
from um982py.messages.record import Record


@dataclass(frozen=True, slots=True)
class DecodedMessage:
    """One inner message paired with the catalogue entry that describes it."""

    message_id: int
    declared_length: int
    family: BasebandMessageFamily | None
    record: Record | None

    @property
    def ignored(self) -> bool:
        """True when the receiver ignores the ID by default."""
        return self.family is BasebandMessageFamily.IGNORED

    @property
    def unknown(self) -> bool:
        """True when the ID lies outside the catalogue range 19..203."""
        return self.family is None

    @property
    def decoded(self) -> bool:
        """True when the payload covered the field extent."""
        return self.record is not None


@dataclass(frozen=True, slots=True)
class MessageCount:
    """How often one inner message ID appears across the containers."""

    message_id: int
    count: int
    family: BasebandMessageFamily | None

    @property
    def ignored(self) -> bool:
        """True when the receiver drops this message ID."""
        return self.family is BasebandMessageFamily.IGNORED

    @property
    def unknown(self) -> bool:
        """True when the catalogue has no entry for this message ID."""
        return self.family is None


@dataclass(frozen=True, slots=True)
class ContainerSummary:
    """Header fields and inner message IDs of one container."""

    sequence: int
    major_version: int
    measurement_sync_tag: int
    antenna_id: int
    frequency_code: int
    interval: int
    declared_length: int
    message_ids: tuple[int, ...]

    def manifest(self) -> dict[str, object]:
        """Plain dictionary for the JSON writer."""
        return {
            "sequence": self.sequence,
            "major_version": self.major_version,
            "measurement_sync_tag": self.measurement_sync_tag,
            "antenna_id": self.antenna_id,
            "frequency_code": self.frequency_code,
            "interval": self.interval,
            "declared_length": self.declared_length,
            "message_ids": list(self.message_ids),
        }


@dataclass(frozen=True, slots=True)
class CaptureReport:
    """Summary of one raw byte capture."""

    containers: tuple[ContainerSummary, ...]
    discarded_bytes: int
    """Bytes that belong to no container."""

    message_count: int
    histogram: tuple[MessageCount, ...]
    notices: tuple[str, ...]
    unknown_ids: tuple[int, ...]
    ignored_ids: tuple[int, ...]

    def manifest(self) -> dict[str, object]:
        """Plain dictionary for the JSON writer."""
        return {
            "containers": [container.manifest() for container in self.containers],
            "container_count": len(self.containers),
            "discarded_bytes": self.discarded_bytes,
            "message_count": self.message_count,
            "histogram": [
                {
                    "message_id": entry.message_id,
                    "count": entry.count,
                    "family": None if entry.family is None else entry.family.value,
                }
                for entry in self.histogram
            ],
            "notices": list(self.notices),
            "unknown_ids": list(self.unknown_ids),
            "ignored_ids": list(self.ignored_ids),
        }


@dataclass(frozen=True, slots=True)
class CatalogueSummary:
    """Shape of the inner message catalogue."""

    first_id: int
    last_id: int
    entries: int
    ignored: int
    undecoded: int

    def manifest(self) -> dict[str, object]:
        """Plain dictionary for the JSON writer."""
        return {
            "first_id": self.first_id,
            "last_id": self.last_id,
            "entries": self.entries,
            "ignored": self.ignored,
            "undecoded": self.undecoded,
        }


def container_summary(container: RawBasebandPacket) -> ContainerSummary:
    """Summarise the header fields and the inner message IDs of a container."""
    header = BasebandHeader.from_bytes(container.raw)
    return ContainerSummary(
        sequence=header.sequence,
        major_version=header.major_version,
        measurement_sync_tag=header.measurement_sync_tag,
        antenna_id=header.antenna_id,
        frequency_code=header.frequency_code,
        interval=header.interval,
        declared_length=container.declared_length,
        message_ids=tuple(message.message_id for message in container.messages),
    )


def decoded_messages(container: RawBasebandPacket) -> tuple[DecodedMessage, ...]:
    """Decode each inner message, keeping undecodable payloads visible."""
    decoded = []
    for message in container.messages:
        entry = BASEBAND_MESSAGE_CATALOGUE.get(message.message_id)
        record: Record | None = None
        try:
            record = decode_message_payload(message.message_id, message.payload)
        except ProtocolError:
            record = None
        decoded.append(
            DecodedMessage(
                message_id=message.message_id,
                declared_length=message.declared_length,
                family=None if entry is None else entry.family,
                record=record,
            )
        )
    return tuple(decoded)


def histogram(messages: Iterable[DecodedMessage]) -> tuple[MessageCount, ...]:
    """Count messages per ID, ordered by ascending message ID."""
    counts: dict[int, int] = {}
    families: dict[int, BasebandMessageFamily | None] = {}
    for message in messages:
        counts[message.message_id] = counts.get(message.message_id, 0) + 1
        families[message.message_id] = message.family
    return tuple(
        MessageCount(message_id, counts[message_id], families[message_id])
        for message_id in sorted(counts)
    )


def read_containers(raw: bytes) -> tuple[RawBasebandPacket, ...]:
    """Recover every complete container from a captured byte stream."""
    return BasebandStream().feed(raw)


def report(raw: bytes) -> CaptureReport:
    """Summarise the containers, messages and notices found in ``raw``."""
    containers = BasebandStream().feed(raw)
    messages = tuple(
        message for container in containers for message in decoded_messages(container)
    )
    covered = sum(container.declared_length for container in containers)
    return CaptureReport(
        containers=tuple(container_summary(container) for container in containers),
        discarded_bytes=len(raw) - covered,
        message_count=len(messages),
        histogram=histogram(messages),
        notices=tuple(sorted({notice.name for notice in scan_notices(raw)})),
        unknown_ids=tuple(
            sorted({message.message_id for message in messages if message.unknown})
        ),
        ignored_ids=tuple(
            sorted({message.message_id for message in messages if message.ignored})
        ),
    )


def catalogue_summary() -> CatalogueSummary:
    """Describe the catalogue so its coverage can be checked."""
    identifiers = sorted(BASEBAND_MESSAGE_CATALOGUE)
    specs = BASEBAND_MESSAGE_CATALOGUE.values()
    return CatalogueSummary(
        first_id=identifiers[0],
        last_id=identifiers[-1],
        entries=len(identifiers),
        ignored=sum(1 for spec in specs if spec.ignored),
        undecoded=sum(1 for spec in specs if not spec.classified),
    )


__all__ = [
    "CaptureReport",
    "CatalogueSummary",
    "ContainerSummary",
    "DecodedMessage",
    "MessageCount",
    "catalogue_summary",
    "container_summary",
    "decoded_messages",
    "field_coverage",
    "histogram",
    "read_containers",
    "report",
]


@dataclass(frozen=True, slots=True)
class FieldCoverage:
    """Share of catalogue fields whose meaning has been verified."""

    messages: int
    described: int
    verified: int
    unverified: int
    verified_ratio: float


def field_coverage() -> FieldCoverage:
    """Count described, verified and unverified fields across the catalogue.

    The receiver debug channel is only partly documented, so a field that is
    decoded but not verified is kept visible instead of being presented as a
    measurement.  This census is the progress meter for promoting fields.
    """
    described = verified = unverified = 0
    for spec in BASEBAND_MESSAGE_CATALOGUE.values():
        if not spec.fields:
            continue
        described += 1
        for field in spec.fields:
            if field.semantic == "verified":
                verified += 1
            else:
                unverified += 1
    total = verified + unverified
    return FieldCoverage(
        messages=len(BASEBAND_MESSAGE_CATALOGUE),
        described=described,
        verified=verified,
        unverified=unverified,
        verified_ratio=verified / total if total else 0.0,
    )
