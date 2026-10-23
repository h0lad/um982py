"""Selects the elevation mask that keeps the required satellites."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from um982py.geodesy import elevation_mask_filter, records_from
from um982py.messages import Record

GRID = 1.0
"""Mask step in degrees because receivers accept whole-degree elevation masks."""

MINIMUM_SATELLITES_FOR_PDOP = 4
"""Four observations are the smallest set that fixes position and clock."""


@dataclass(frozen=True, slots=True)
class SkySatellite:
    """One satellite position in the local sky, in degrees."""

    prn: int
    elevation: float
    azimuth: float

    @property
    def line_of_sight(self) -> tuple[float, float, float]:
        """Unit vector from the antenna to the satellite in east, north, up."""
        return line_of_sight(self.azimuth, self.elevation)


@dataclass(frozen=True, slots=True)
class MaskSolution:
    """The selected mask, the PDOP it achieves and the satellites it keeps."""

    mask: float
    pdop: float
    satellites: int

    def manifest(self) -> dict[str, object]:
        """Plain dictionary for the JSON writer."""
        return {
            "mask": self.mask,
            "pdop": self.pdop,
            "satellites": self.satellites,
        }


def line_of_sight(azimuth: float, elevation: float) -> tuple[float, float, float]:
    """Unit vector from the antenna to a satellite in east, north, up."""
    azimuth_radians = math.radians(azimuth)
    elevation_radians = math.radians(elevation)
    ground = math.cos(elevation_radians)
    return (
        ground * math.sin(azimuth_radians),
        ground * math.cos(azimuth_radians),
        math.sin(elevation_radians),
    )


def normal_matrix(
    azimuths: Sequence[float], elevations: Sequence[float]
) -> list[list[float]]:
    """Form ``G^T G`` for unit line-of-sight rows and a receiver clock column."""
    if len(azimuths) != len(elevations):
        raise ValueError("azimuths and elevations must have equal length")
    if not azimuths:
        raise ValueError("at least one sky position is required")
    rows = [
        [*line_of_sight(azimuth, elevation), 1.0]
        for azimuth, elevation in zip(azimuths, elevations, strict=True)
    ]
    size = len(rows[0])
    return [
        [sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)
    ]


def inverse(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Invert a square matrix with Gauss-Jordan elimination.

    Raise ``ValueError`` if the matrix is singular.
    """
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        raise ValueError("matrix must be square and nonempty")
    augmented = [
        [*row, *(1.0 if i == j else 0.0 for j in range(size))]
        for i, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("matrix is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        lead = augmented[column][column]
        augmented[column] = [value / lead for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    value - factor * lead_value
                    for value, lead_value in zip(
                        augmented[row], augmented[column], strict=True
                    )
                ]
    return [row[size:] for row in augmented]


def pdop(azimuths: Sequence[float], elevations: Sequence[float]) -> float:
    """Return PDOP, or infinity for fewer than four satellites or singular geometry."""
    if len(elevations) < MINIMUM_SATELLITES_FOR_PDOP:
        return math.inf
    try:
        covariant = inverse(normal_matrix(azimuths, elevations))
    except ValueError:
        return math.inf
    diagonal = covariant[0][0] + covariant[1][1] + covariant[2][2]
    return math.sqrt(max(0.0, diagonal))


def retained(
    satellites: Sequence[SkySatellite], mask: float
) -> tuple[SkySatellite, ...]:
    """Keep the satellites at or above ``mask`` degrees of elevation."""
    return tuple(satellite for satellite in satellites if satellite.elevation >= mask)


def pdop_at_mask(satellites: Sequence[SkySatellite], mask: float) -> float:
    """PDOP of the satellites the mask retains."""
    kept = retained(satellites, mask)
    return pdop(
        [satellite.azimuth for satellite in kept],
        [satellite.elevation for satellite in kept],
    )


def sky_from_satvis(records: Iterable[Record]) -> tuple[SkySatellite, ...]:
    """Convert decoded satellite records into sky positions."""
    return tuple(
        SkySatellite(
            prn=record.integer("prn"),
            elevation=record.real("elevation"),
            azimuth=record.real("azimuth"),
        )
        for record in records
    )


def sky_from_satvis_log(
    record: Record, *, minimum_elevation: float = 0.0
) -> tuple[SkySatellite, ...]:
    """Build sky positions from the satellite records of one SATVIS2 frame."""
    return sky_from_satvis(
        elevation_mask_filter(records_from(record, "satellites"), minimum_elevation)
    )


def solution_at(
    satellites: Sequence[SkySatellite], mask: float, *, minimum_satellites: int
) -> MaskSolution | None:
    """Evaluate one mask, or ``None`` when it keeps too few satellites."""
    kept = retained(satellites, mask)
    if len(kept) < minimum_satellites:
        return None
    value = pdop(
        [satellite.azimuth for satellite in kept],
        [satellite.elevation for satellite in kept],
    )
    if math.isinf(value):
        return None
    return MaskSolution(mask=mask, pdop=value, satellites=len(kept))


def highest_feasible_mask(
    satellites: Sequence[SkySatellite],
    *,
    minimum_satellites: int = MINIMUM_SATELLITES_FOR_PDOP,
    ceiling: float = 90.0,
) -> MaskSolution | None:
    """Highest grid mask keeping the minimum count, from the order statistic."""
    if minimum_satellites < MINIMUM_SATELLITES_FOR_PDOP:
        raise ValueError("PDOP needs at least four satellites")
    if not math.isfinite(ceiling) or not 0 <= ceiling <= 90:
        raise ValueError("ceiling must be in 0..90 degrees")
    ordered = sorted(satellites, key=lambda satellite: -satellite.elevation)
    if len(ordered) < minimum_satellites:
        return None
    reference = ordered[minimum_satellites - 1].elevation
    mask = float(min(math.floor(reference), math.floor(ceiling)))
    while mask >= 0:
        solution = solution_at(satellites, mask, minimum_satellites=minimum_satellites)
        if solution is not None:
            return solution
        mask -= GRID
    return None


def brute_force_mask(
    satellites: Sequence[SkySatellite],
    *,
    minimum_satellites: int = MINIMUM_SATELLITES_FOR_PDOP,
    ceiling: float = 90.0,
) -> MaskSolution | None:
    """Highest grid mask that keeps the minimum count, found by scanning every step."""
    if minimum_satellites < MINIMUM_SATELLITES_FOR_PDOP:
        raise ValueError("PDOP needs at least four satellites")
    if not math.isfinite(ceiling) or not 0 <= ceiling <= 90:
        raise ValueError("ceiling must be in 0..90 degrees")
    best: MaskSolution | None = None
    for step in range(math.floor(ceiling) + 1):
        solution = solution_at(
            satellites, float(step), minimum_satellites=minimum_satellites
        )
        if solution is not None:
            best = solution
    return best


__all__ = [
    "GRID",
    "MINIMUM_SATELLITES_FOR_PDOP",
    "MaskSolution",
    "SkySatellite",
    "brute_force_mask",
    "highest_feasible_mask",
    "inverse",
    "line_of_sight",
    "normal_matrix",
    "pdop",
    "pdop_at_mask",
    "retained",
    "sky_from_satvis",
    "sky_from_satvis_log",
    "solution_at",
]
