"""Checks dual-antenna heading, sky view and spoof indicators."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from examples.satellite_monitor import constellation_of
from um982py.capture import record_epoch
from um982py.geodesy import enu_from_ecef, records_from
from um982py.messages.record import Record

FULL_TURN_DEGREES = 360.0
FLAT_FLOOR_DEGREES = 0.1
SIGMA_MULTIPLE = 3.0
RESOLVABLE_SIGMA_DEGREES = 90.0
SKY_TOLERANCE_DEGREES = 0.2
SKY_FRAMES_PER_SNAPSHOT = 7
"""SATVIS2 frames per request: one per constellation the receiver tracks."""

__all__ = [
    "FLAT_FLOOR_DEGREES",
    "RESOLVABLE_SIGMA_DEGREES",
    "SIGMA_MULTIPLE",
    "SKY_FRAMES_PER_SNAPSHOT",
    "SKY_TOLERANCE_DEGREES",
    "Alarm",
    "BearingCandidates",
    "EcefBaseline",
    "EnuBaseline",
    "HeadingAgreement",
    "HeadingOffset",
    "SkyComparison",
    "SkyDisagreement",
    "SkyEntry",
    "SkyView",
    "SpoofStatus",
    "alarms",
    "apply_heading_offset",
    "bearing_candidates",
    "circular_difference",
    "compare_headings",
    "compare_sky",
    "compare_snapshots",
    "resolve_bearing",
    "sky_snapshots",
]


class Alarm(StrEnum):
    """Reason the dual-antenna check refuses to trust the solution."""

    BASELINE_HEADING = "BASELINE_HEADING"
    SKY_VIEW = "SKY_VIEW"
    SPOOF_INDICATOR = "SPOOF_INDICATOR"


@dataclass(frozen=True, slots=True)
class EnuBaseline:
    """East, north, up baseline in metres and its component deviations."""

    east: float
    north: float
    up: float
    sigma_east: float
    sigma_north: float
    sigma_up: float

    @classmethod
    def from_record(cls, record: Record) -> EnuBaseline:
        """Build the baseline from a decoded BSLNENUHD record."""
        return cls(
            east=record.real("delta_1"),
            north=record.real("delta_2"),
            up=record.real("delta_3"),
            sigma_east=record.real("std_1"),
            sigma_north=record.real("std_2"),
            sigma_up=record.real("std_3"),
        )

    def negated(self) -> EnuBaseline:
        """The same baseline measured from the other antenna input."""
        return EnuBaseline(
            east=-self.east,
            north=-self.north,
            up=-self.up,
            sigma_east=self.sigma_east,
            sigma_north=self.sigma_north,
            sigma_up=self.sigma_up,
        )

    @property
    def horizontal_length(self) -> float:
        """Length of the horizontal projection in metres."""
        return math.hypot(self.east, self.north)

    @property
    def length(self) -> float:
        """Full baseline length in metres."""
        return math.sqrt(self.east**2 + self.north**2 + self.up**2)

    @property
    def heading(self) -> float:
        """Clockwise angle from true north to the horizontal baseline, in degrees."""
        return math.degrees(math.atan2(self.east, self.north)) % FULL_TURN_DEGREES

    @property
    def pitch(self) -> float:
        """Angle of the baseline above the horizontal plane, in degrees."""
        if self.length <= 0:
            raise ValueError("baseline length must be positive")
        return math.degrees(math.asin(max(-1.0, min(1.0, self.up / self.length))))

    @property
    def heading_sigma(self) -> float:
        """Heading standard deviation in degrees propagated from the deviations."""
        if self.horizontal_length <= 0:
            raise ValueError("horizontal baseline must be positive")
        psi = math.radians(self.heading)
        perpendicular = math.hypot(
            self.sigma_east * math.cos(psi), self.sigma_north * math.sin(psi)
        )
        return math.degrees(perpendicular / self.horizontal_length)


@dataclass(frozen=True, slots=True)
class EcefBaseline:
    """Earth-centred baseline in metres and its component deviations."""

    x: float
    y: float
    z: float
    sigma_x: float
    sigma_y: float
    sigma_z: float

    @classmethod
    def from_record(cls, record: Record) -> EcefBaseline:
        """Build the baseline from a decoded BSLNXYZHD record."""
        return cls(
            x=record.real("delta_1"),
            y=record.real("delta_2"),
            z=record.real("delta_3"),
            sigma_x=record.real("std_1"),
            sigma_y=record.real("std_2"),
            sigma_z=record.real("std_3"),
        )

    def negated(self) -> EcefBaseline:
        """The same baseline measured from the other antenna input."""
        return EcefBaseline(
            x=-self.x,
            y=-self.y,
            z=-self.z,
            sigma_x=self.sigma_x,
            sigma_y=self.sigma_y,
            sigma_z=self.sigma_z,
        )

    def to_enu(self, latitude: float, longitude: float) -> EnuBaseline:
        """Rotate the baseline into local east, north, up metres."""
        east, north, up = enu_from_ecef(self.x, self.y, self.z, latitude, longitude)
        sigma_east, sigma_north, sigma_up = _rotated_sigma(
            (self.sigma_x, self.sigma_y, self.sigma_z), latitude, longitude
        )
        return EnuBaseline(east, north, up, sigma_east, sigma_north, sigma_up)


_UNIT_AXES: tuple[tuple[float, float, float], ...] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


def _rotated_sigma(
    sigma: tuple[float, float, float], latitude: float, longitude: float
) -> tuple[float, float, float]:
    rows = tuple(enu_from_ecef(*axis, latitude, longitude) for axis in _UNIT_AXES)
    combined = tuple(
        math.sqrt(
            sum(
                (row[index] * value) ** 2
                for row, value in zip(rows, sigma, strict=True)
            )
        )
        for index in range(3)
    )
    return combined[0], combined[1], combined[2]


@dataclass(frozen=True, slots=True)
class HeadingOffset:
    """Mount offset reported by HEADINGOFFSET, in degrees."""

    heading: float
    pitch: float

    @classmethod
    def from_record(cls, record: Record) -> HeadingOffset:
        """Build the offset from a decoded HEADINGOFFSET record."""
        return cls(record.real("heading"), record.real("pitch"))


def apply_heading_offset(baseline: EnuBaseline, offset: HeadingOffset) -> EnuBaseline:
    """Rotate a baseline into the reported frame by removing the mount offset."""
    heading = math.radians(baseline.heading - offset.heading)
    pitch = math.radians(baseline.pitch - offset.pitch)
    horizontal = baseline.length * math.cos(pitch)
    return EnuBaseline(
        east=horizontal * math.sin(heading),
        north=horizontal * math.cos(heading),
        up=baseline.length * math.sin(pitch),
        sigma_east=baseline.sigma_east,
        sigma_north=baseline.sigma_north,
        sigma_up=baseline.sigma_up,
    )


def circular_difference(first: float, second: float) -> float:
    """Signed difference ``first - second`` folded into -180..180 degrees."""
    return (first - second + 180.0) % FULL_TURN_DEGREES - 180.0


@dataclass(frozen=True, slots=True)
class HeadingAgreement:
    """Agreement of a baseline heading with an independent heading."""

    heading: float
    reference: float
    sigma: float

    @property
    def difference(self) -> float:
        """Signed heading difference in degrees."""
        return circular_difference(self.heading, self.reference)

    @property
    def tolerance(self) -> float:
        """Largest accepted difference in degrees."""
        return max(FLAT_FLOOR_DEGREES, SIGMA_MULTIPLE * self.sigma)

    @property
    def resolvable(self) -> bool:
        """Whether the propagated deviation leaves the heading meaningful."""
        return self.sigma <= RESOLVABLE_SIGMA_DEGREES

    @property
    def consistent(self) -> bool:
        """Whether the headings agree, abstaining when the heading is unobservable."""
        return not self.resolvable or abs(self.difference) <= self.tolerance


def compare_headings(baseline: EnuBaseline, reference: EnuBaseline) -> HeadingAgreement:
    """Compare two baseline headings with the deviation of both propagated."""
    if baseline.horizontal_length <= 0:
        raise ValueError("horizontal baseline must be positive")
    return HeadingAgreement(
        heading=baseline.heading,
        reference=reference.heading,
        sigma=math.hypot(baseline.heading_sigma, reference.heading_sigma),
    )


@dataclass(frozen=True, slots=True)
class SkyEntry:
    """One satellite of a SATVIS2 frame: angles in degrees."""

    prn: int
    elevation: float
    azimuth: float


@dataclass(frozen=True, slots=True)
class SkyView:
    """Satellite angles of one SATVIS2 frame, indexed by pseudorandom number."""

    satellites: tuple[SkyEntry, ...]
    constellation: str = ""

    @classmethod
    def from_record(cls, record: Record) -> SkyView:
        """Build the view from a SATVIS2 frame of one constellation."""
        return cls(
            tuple(
                SkyEntry(
                    prn=satellite.integer("prn"),
                    elevation=satellite.real("elevation"),
                    azimuth=satellite.real("azimuth"),
                )
                for satellite in records_from(record, "satellites")
            ),
            constellation=constellation_of(record).value,
        )

    def by_prn(self) -> Mapping[int, SkyEntry]:
        """Satellite entries keyed by pseudorandom number."""
        return {satellite.prn: satellite for satellite in self.satellites}


@dataclass(frozen=True, slots=True)
class SkyDisagreement:
    """Angle difference of one satellite seen by both antennas."""

    prn: int
    elevation_difference: float
    azimuth_difference: float
    tolerance: float

    @property
    def consistent(self) -> bool:
        """Whether both angles agree within the reported resolution."""
        return (
            abs(self.elevation_difference) <= self.tolerance
            and abs(self.azimuth_difference) <= self.tolerance
        )


@dataclass(frozen=True, slots=True)
class SkyComparison:
    """Comparison of the two antennas' views of one constellation."""

    shared: tuple[int, ...]
    absent: tuple[int, ...]
    disagreements: tuple[SkyDisagreement, ...]

    @property
    def consistent(self) -> bool:
        """Whether every satellite seen by both antennas has the same angles."""
        return all(disagreement.consistent for disagreement in self.disagreements)


def compare_sky(
    first: SkyView, second: SkyView, *, tolerance: float = SKY_TOLERANCE_DEGREES
) -> SkyComparison:
    """Compare two antenna sky views satellite by satellite."""
    first_by_prn, second_by_prn = first.by_prn(), second.by_prn()
    shared = sorted(set(first_by_prn) & set(second_by_prn))
    return SkyComparison(
        shared=tuple(shared),
        absent=tuple(sorted(set(first_by_prn) ^ set(second_by_prn))),
        disagreements=tuple(
            SkyDisagreement(
                prn=prn,
                elevation_difference=first_by_prn[prn].elevation
                - second_by_prn[prn].elevation,
                azimuth_difference=circular_difference(
                    first_by_prn[prn].azimuth, second_by_prn[prn].azimuth
                ),
                tolerance=tolerance,
            )
            for prn in shared
        ),
    )


def sky_snapshots(records: Iterable[Record]) -> tuple[tuple[SkyView, ...], ...]:
    """Group SATVIS2 frames into one sky view per constellation per request."""
    snapshots: list[tuple[SkyView, ...]] = []
    current: list[SkyView] = []
    seen: set[str] = set()
    previous: float | None = None
    for record in records:
        view = SkyView.from_record(record)
        epoch = record_epoch(record) if record.message is not None else None
        if current and (epoch != previous or view.constellation in seen):
            snapshots.append(tuple(current))
            current, seen = [], set()
        current.append(view)
        seen.add(view.constellation)
        previous = epoch
    if current:
        snapshots.append(tuple(current))
    return tuple(snapshots)


def compare_snapshots(
    first: Sequence[SkyView], second: Sequence[SkyView]
) -> tuple[SkyComparison, ...]:
    """Compare two snapshots constellation by constellation."""
    if all(view.constellation for view in (*first, *second)):
        right_by_name = {view.constellation: view for view in second}
        return tuple(
            compare_sky(view, right_by_name[view.constellation])
            for view in first
            if view.constellation in right_by_name
        )
    return tuple(
        compare_sky(left, right) for left, right in zip(first, second, strict=False)
    )


@dataclass(frozen=True, slots=True)
class SpoofStatus:
    """SPOOFINFO position type and spoofing indicator."""

    position_type: str
    indicator: int

    @classmethod
    def from_record(cls, record: Record) -> SpoofStatus:
        """Build the status from a decoded SPOOFINFO record."""
        return cls(str(record["position_type"]), record.integer("spoof_indicator"))

    @property
    def spoofed(self) -> bool:
        """Whether the receiver reports a non-zero spoofing indicator."""
        return self.indicator != 0


def alarms(
    heading: HeadingAgreement | None,
    skies: Sequence[SkyComparison],
    spoof: SpoofStatus | None,
) -> tuple[Alarm, ...]:
    """Alarms raised by the heading, sky-view and spoof-indicator paths."""
    raised: list[Alarm] = []
    if heading is not None and not heading.consistent:
        raised.append(Alarm.BASELINE_HEADING)
    if any(not comparison.consistent for comparison in skies):
        raised.append(Alarm.SKY_VIEW)
    if spoof is not None and spoof.spoofed:
        raised.append(Alarm.SPOOF_INDICATOR)
    return tuple(raised)


FULL_TURN = 360.0


@dataclass(frozen=True, slots=True)
class BearingCandidates:
    """Two cone-symmetric bearings of one source seen by a two-element baseline."""

    separation_degrees: float
    candidate_bearings: tuple[float, float]
    leverage: float
    distinct: bool


def bearing_candidates(
    phase_difference_cycles: float,
    *,
    baseline_heading: float,
    baseline_length_m: float,
    wavelength_m: float,
) -> BearingCandidates:
    """Bearings of a source from the inter-antenna phase, without resolving the cone.

    A single baseline measures ``cos`` of the angle between the baseline axis
    and the source direction, so every measurement yields two mirror bearings
    about the baseline heading.  ``leverage`` is the sine of that separation:
    it vanishes when the source lies on the baseline axis, where the two
    candidates coincide and the geometry carries no bearing information.
    """
    for name, value in (
        ("phase difference", phase_difference_cycles),
        ("baseline heading", baseline_heading),
        ("baseline length", baseline_length_m),
        ("wavelength", wavelength_m),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if baseline_length_m <= 0 or wavelength_m <= 0:
        raise ValueError("baseline length and wavelength must be positive")
    cosine = phase_difference_cycles * wavelength_m / baseline_length_m
    if abs(cosine) > 1.0:
        raise ValueError("phase difference exceeds the baseline")
    separation = math.degrees(math.acos(cosine))
    first = (baseline_heading + separation) % FULL_TURN
    second = (baseline_heading - separation) % FULL_TURN
    leverage = abs(math.sin(math.radians(separation)))
    return BearingCandidates(
        separation_degrees=separation,
        candidate_bearings=(first, second),
        leverage=leverage,
        distinct=leverage > 1e-9,
    )


def resolve_bearing(candidates: BearingCandidates, reference_heading: float) -> float:
    """Pick the mirror bearing closest to an independent heading prior."""
    if not math.isfinite(reference_heading):
        raise ValueError("reference heading must be finite")
    return min(
        candidates.candidate_bearings,
        key=lambda bearing: abs(
            (bearing - reference_heading + FULL_TURN / 2) % FULL_TURN - FULL_TURN / 2
        ),
    )
