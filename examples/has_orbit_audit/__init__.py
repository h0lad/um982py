"""Applies Galileo HAS orbit and clock corrections to broadcast ephemerides."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from um982py.experimental.orbit import KeplerElements, orbit_state, system_of
from um982py.gnss import SPEED_OF_LIGHT, WEEK_SECONDS, has_epoch, unwrap_time
from um982py.measurement import gps_epoch
from um982py.messages.corrections import (
    HasSatelliteCorrection,
    has_satellite_corrections,
    has_validity_seconds,
)
from um982py.messages.record import Record
from um982py.stats import Vector, cross, finite, unit

HAS_SYSTEMS = {0: "G", 2: "E"}
"""HAS GNSS identifiers mapped to RINEX and SP3 system letters."""

SISRE_WEIGHTS = {"G": (0.98, 1.0 / 49.0), "E": (0.98, 1.0 / 61.0)}
"""Radial and squared angular SISRE weights, Montenbruck et al. (2018), table 1."""


@dataclass(frozen=True, slots=True)
class BroadcastState:
    """ECEF position, velocity and ionosphere-free clock of one ephemeris.

    The clock is the broadcast polynomial plus the relativistic term without
    a group delay, the quantity HAS corrects (HAS SIS ICD, Eq. 23).
    """

    satellite: str
    issue: int
    position: Vector
    velocity: Vector
    clock_seconds: float


@dataclass(frozen=True, slots=True)
class HasSnapshot:
    """The corrections in force from one clock block, with their epochs."""

    orbit_epoch: float
    clock_epoch: float
    orbit_valid_until: float
    clock_valid_until: float
    corrections: Mapping[tuple[int, int], HasSatelliteCorrection]


def ntw_axes(position: Vector, velocity: Vector) -> tuple[Vector, Vector, Vector]:
    """Radial, in-track and cross-track unit vectors of HAS SIS ICD Eq. 18-20.

    The axes use the ECEF position and velocity of the broadcast orbit.
    """
    in_track = unit(velocity)
    cross_track = unit(cross(position, velocity))
    return cross(in_track, cross_track), in_track, cross_track


def apply_has(
    state: BroadcastState, correction: HasSatelliteCorrection
) -> tuple[Vector, float] | None:
    """Corrected position (Eq. 22) and clock (Eq. 23), or None if unusable."""
    components = (correction.radial, correction.in_track, correction.cross_track)
    if correction.clock is None or correction.clock.meters is None:
        return None
    if any(component.meters is None for component in components):
        return None
    radial, in_track, cross_track = ntw_axes(state.position, state.velocity)
    n, t, w = (component.meters or 0.0 for component in components)
    position = tuple(
        value + n * e_n + t * e_t + w * e_w
        for value, e_n, e_t, e_w in zip(
            state.position, radial, in_track, cross_track, strict=True
        )
    )
    return (
        (position[0], position[1], position[2]),
        state.clock_seconds + correction.clock.meters / SPEED_OF_LIGHT,
    )


def ephemeris_identity(record: Record) -> tuple[str, int]:
    """SP3 satellite name and HAS issue (IODnav or IODE) of an ephemeris."""
    system = system_of(record)
    if system == "GALILEO":
        return f"E{record.integer('satid'):02d}", record.integer("iodnav")
    if system == "GPS":
        return f"G{record.integer('prn'):02d}", record.integer("iode1")
    raise ValueError(f"HAS does not correct {system} ephemerides")


def broadcast_state(record: Record, epoch: float) -> BroadcastState:
    """Propagate a GPSEPH or GALEPH record with its HAS reference clock.

    Galileo uses the I/NAV clock, the HAS reference navigation message.
    """
    finite(epoch)
    system = system_of(record)
    satellite, issue = ephemeris_identity(record)
    prn = int(satellite[1:])
    elements = KeplerElements.from_record(record, inav=True)
    toe = unwrap_time(epoch, elements.toe, WEEK_SECONDS)
    dt = epoch - toe
    state = orbit_state(elements, dt, system=system, prn=prn)
    before = orbit_state(elements, dt - 0.5, system=system, prn=prn)
    after = orbit_state(elements, dt + 0.5, system=system, prn=prn)
    return BroadcastState(
        satellite,
        issue,
        (state.x, state.y, state.z),
        (after.x - before.x, after.y - before.y, after.z - before.z),
        state.clock_bias + elements.tgd,
    )


def usable_ephemeris(record: Record) -> bool:
    """Healthy GPS LNAV or Galileo I/NAV data with a consistent issue."""
    if system_of(record) == "GALILEO":
        return all(
            record.integer(name) == 0
            for name in ("e1bhealth", "e5bhealth", "e1bdvs", "e5bdvs")
        )
    return (
        record.integer("health") == 0
        and record.integer("iode1") == record.integer("iode2")
        and record.integer("iodc") & 255 == record.integer("iode1")
    )


def correction_timeline(records: Iterable[Record]) -> tuple[HasSnapshot, ...]:
    """Pair each clock block with the latest mask and orbit of its IOD set.

    ``records`` holds E6MASKBLOCK, E6ORBITBLOCK and E6CLOCKFULLBLOCK records
    in reception order. Snapshot epochs come from each block's time of hour.
    """
    masks: dict[tuple[int, int], Record] = {}
    orbits: dict[tuple[int, int], tuple[float, Record]] = {}
    snapshots: list[HasSnapshot] = []
    for record in records:
        if record.message is None:
            raise ValueError("timestamped HAS records are required")
        key = record.integer("mask_id"), record.integer("iod_set_id")
        epoch = has_epoch(gps_epoch(record.message), record.integer("toh"))
        if record.name == "E6MASKBLOCK":
            masks[key] = record
        elif record.name == "E6ORBITBLOCK":
            orbits[key] = epoch, record
        elif record.name == "E6CLOCKFULLBLOCK" and key in masks and key in orbits:
            orbit_epoch, orbit = orbits[key]
            orbit_validity = has_validity_seconds(orbit.integer("validity_interval"))
            clock_validity = has_validity_seconds(record.integer("validity_interval"))
            if orbit_validity is None or clock_validity is None:
                continue
            snapshots.append(
                HasSnapshot(
                    orbit_epoch,
                    epoch,
                    orbit_epoch + orbit_validity,
                    epoch + clock_validity,
                    has_satellite_corrections(masks[key], orbit, record),
                )
            )
    return tuple(snapshots)


def snapshot_at(snapshots: Sequence[HasSnapshot], epoch: float) -> HasSnapshot | None:
    """The latest snapshot whose orbit and clock are both valid at ``epoch``."""
    valid = [
        snapshot
        for snapshot in snapshots
        if snapshot.clock_epoch <= epoch <= snapshot.clock_valid_until
        and snapshot.orbit_epoch <= epoch <= snapshot.orbit_valid_until
    ]
    return max(valid, key=lambda snapshot: snapshot.clock_epoch, default=None)


def has_key(satellite: str) -> tuple[int, int]:
    """The HAS (GNSS ID, PRN) key of an SP3 satellite identifier."""
    for gnss_id, letter in HAS_SYSTEMS.items():
        if satellite.startswith(letter):
            return gnss_id, int(satellite[1:])
    raise ValueError(f"HAS does not correct {satellite}")


def apc_reference(position: Vector, pco_z: float) -> Vector:
    """Move a centre-of-mass position to a nadir-offset antenna phase centre."""
    finite(*position, pco_z)
    radial = unit(position)
    return (
        position[0] - pco_z * radial[0],
        position[1] - pco_z * radial[1],
        position[2] - pco_z * radial[2],
    )


def clock_aligned(differences: Mapping[str, float]) -> dict[str, float]:
    """Remove the per-epoch median clock difference, the product's clock datum."""
    if len(differences) < 4:
        return {}
    datum = median(differences.values())
    return {satellite: value - datum for satellite, value in differences.items()}
