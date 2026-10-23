"""PPP-B2b age and issue-of-data checks without mask decoding."""

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from um982py._b2b import b2b_epoch
from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.messages.enums import PositionType
from um982py.stats import finite

_CORRECTION_TYPES = {
    PositionType.PSRDIFF,
    PositionType.L1_FLOAT,
    PositionType.IONOFREE_FLOAT,
    PositionType.NARROW_FLOAT,
    PositionType.L1_INT,
    PositionType.WIDE_INT,
    PositionType.NARROW_INT,
    PositionType.INS_PSRDIFF,
    PositionType.INS_RTKFLOAT,
    PositionType.INS_RTKFIXED,
}


def stale_correction(
    position_type: object, age_s: object, *, max_age_s: float = 10.0
) -> bool:
    """Whether a differential or RTK fix relies on old corrections."""
    try:
        if isinstance(position_type, str):
            kind = PositionType[position_type]
        elif isinstance(position_type, int):
            kind = PositionType(position_type)
        else:
            return False
    except (KeyError, ValueError):
        return False
    return (
        kind in _CORRECTION_TYPES
        and isinstance(age_s, (int, float))
        and (not math.isfinite(age_s) or age_s < 0 or age_s > max_age_s)
    )


@dataclass(frozen=True, slots=True)
class CorrectionEvent:
    """One correction block with its native satellite slots and issue tags."""

    received: float
    transmitter: int
    kind: str
    epoch: float
    iodssr: int
    iodp: int | None = None
    issues: tuple[tuple[int, int], ...] = ()
    navigation: tuple[tuple[int, int], ...] = ()
    mask: bytes | None = None


@dataclass(frozen=True, slots=True)
class CorrectionCheck:
    """Records correction latency and coherence faults against preceding blocks."""

    received: float
    transmitter: int
    kind: str
    age_seconds: float
    flags: tuple[str, ...]


def audit_corrections(
    events: Sequence[CorrectionEvent],
    *,
    max_age: float = 60.0,
    mask_max_age: float = 300.0,
    navigation_issues: Mapping[int, int] | None = None,
) -> tuple[CorrectionCheck, ...]:
    """Audit preceding mask and orbit issues with independently bounded ages."""
    finite(max_age, mask_max_age)
    if max_age <= 0 or mask_max_age <= 0:
        raise ValueError("age limits must be positive")
    if any(b.received < a.received for a, b in itertools.pairwise(events)):
        raise ValueError("correction events must be in reception order")
    masks: dict[int, CorrectionEvent] = {}
    orbits: dict[tuple[int, int], tuple[int, int, float]] = {}
    output = []
    for event in events:
        finite(event.received, event.epoch)
        if event.kind not in ("mask", "orbit", "clock", "bias", "ura"):
            raise ValueError("unknown correction block kind")
        age = event.received - event.epoch
        flags: list[str] = []
        if age < -1:
            flags.append("future_epoch")
        if age > max_age:
            flags.append("stale_correction")
        usable = -1 <= age <= max_age
        previous = masks.get(event.transmitter)
        if event.kind == "mask":
            if event.mask is None or len(event.mask) != 32 or event.iodp is None:
                raise ValueError("mask blocks need 32 mask bytes and IODP")
            if previous is not None:
                if event.epoch < previous.epoch:
                    flags.append("out_of_order_mask")
                    usable = False
                elif (event.iodssr, event.iodp) == (
                    previous.iodssr,
                    previous.iodp,
                ) and event.mask != previous.mask:
                    flags.append("mask_changed_without_issue")
                    usable = False
            if usable:
                masks[event.transmitter] = event
        else:
            if previous is None:
                flags.append("missing_mask")
            else:
                if event.received - previous.epoch > mask_max_age:
                    flags.append("stale_mask")
                if event.iodssr != previous.iodssr:
                    flags.append("iodssr_mismatch")
                if event.iodp is not None and event.iodp != previous.iodp:
                    flags.append("iodp_mismatch")
            if event.kind == "orbit":
                for slot, iodn in event.navigation:
                    if (
                        navigation_issues is not None
                        and slot in navigation_issues
                        and navigation_issues[slot] != iodn
                    ):
                        flags.append(f"navigation_issue_mismatch:{slot}")
                for slot, issue in event.issues:
                    key = event.transmitter, slot
                    old = orbits.get(key)
                    if old is not None and event.epoch < old[2]:
                        flags.append(f"out_of_order_orbit:{slot}")
                    elif usable and not flags:
                        orbits[key] = event.iodssr, issue, event.epoch
            if event.kind == "clock":
                if not event.issues:
                    flags.append("satellite_mapping_unverified")
                for slot, issue in event.issues:
                    orbit = orbits.get((event.transmitter, slot))
                    if orbit is None:
                        flags.append(f"missing_orbit:{slot}")
                    elif (event.iodssr, issue) != orbit[:2]:
                        flags.append(f"iodcorr_mismatch:{slot}")
                    elif event.received - orbit[2] > max_age:
                        flags.append(f"stale_orbit:{slot}")
        output.append(
            CorrectionCheck(
                event.received,
                event.transmitter,
                event.kind,
                age,
                tuple(dict.fromkeys(flags)),
            )
        )
    return tuple(output)


def correction_events(record: Record) -> tuple[CorrectionEvent, ...]:
    """Extract native metadata without guessing storage order for a PRN mask."""
    if record.message is None:
        raise ValueError("correction record needs a receiver timestamp")
    received = gps_epoch(record.message)
    transmitter = record.integer("prn")
    kind = int(record.name.removeprefix("PPPB2BINFO"))

    def block(
        data: Record, name: str, rows: Sequence[Record] = (), *, explicit: bool = False
    ) -> CorrectionEvent:
        issues = tuple(
            (row.integer("prn"), row.integer("iod_corr"))
            for row in rows
            if explicit and row.integer("prn") > 0
        )
        navigation = tuple(
            (row.integer("prn"), row.integer("iodn"))
            for row in rows
            if name == "orbit" and row.integer("prn") > 0
        )
        iodp = data.integer("iodp") if "iodp" in data and name != "orbit" else None
        mask = data.get("mask")
        return CorrectionEvent(
            received,
            transmitter,
            name,
            b2b_epoch(received, data.integer("seconds_of_day")),
            data.integer("iodssr"),
            iodp,
            issues,
            navigation,
            mask if isinstance(mask, bytes) else None,
        )

    if kind in (6, 7):
        clocks, orbits = record.records("clock")[0], record.records("orbit")[0]
        blocks = []
        if record.integer("num_orbit"):
            blocks.append(
                block(orbits, "orbit", orbits.records("corrections"), explicit=True)
            )
        if record.integer("num_clock"):
            blocks.append(
                block(
                    clocks, "clock", clocks.records("corrections"), explicit=kind == 7
                )
            )
        return tuple(blocks)
    if kind == 2:
        return (block(record, "orbit", record.records("orbit"), explicit=True),)
    return (block(record, {1: "mask", 3: "bias", 4: "clock", 5: "ura"}[kind]),)


def audit_has(
    records: Sequence[Record],
    *,
    max_age: float = 60.0,
    mask_max_age: float = 300.0,
) -> tuple[dict[str, object], ...]:
    """Check HAS time-of-hour, mask ID and IOD-set delivery coherence."""
    finite(max_age, mask_max_age)
    if max_age <= 0 or mask_max_age <= 0:
        raise ValueError("age limits must be positive")
    masks: dict[tuple[int, int], float] = {}
    previous = -math.inf
    output: list[dict[str, object]] = []
    for record in records:
        if not record.name.startswith("E6") or record.message is None:
            raise ValueError("timestamped E6 correction records are required")
        received = gps_epoch(record.message)
        if received < previous:
            raise ValueError("HAS records must be in reception order")
        previous = received
        toh = record.integer("toh")
        if not 0 <= toh < 3600:
            raise ValueError("HAS time of hour must be in 0..3599")
        epoch = math.floor(received / 3600) * 3600 + toh
        if epoch > received:
            epoch -= 3600
        age = received - epoch
        mask_id, iod = record.integer("mask_id"), record.integer("iod_set_id")
        flags = []
        if age > max_age:
            flags.append("stale_correction")
        if record.name == "E6MASKBLOCK":
            if not flags:
                masks[mask_id, iod] = epoch
        elif (mask_id, iod) not in masks:
            flags.append("missing_mask")
        else:
            if received - masks[mask_id, iod] > min(mask_max_age, 1800):
                flags.append("stale_mask")
        output.append(
            {
                "source": record.name,
                "received_gps_seconds": received,
                "age_seconds": age,
                "mask_id": mask_id,
                "iod_set_id": iod,
                "flags": flags,
            }
        )
    return tuple(output)
