"""Dilution of precision from satellite geometry and receiver reports."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from um982py.geodesy import elevation_mask_filter, records_from

if TYPE_CHECKING:
    from um982py.messages.record import Record


@dataclass(frozen=True, slots=True)
class SatelliteGeometry:
    """Azimuth and elevation of one satellite in degrees."""

    azimuth: float
    elevation: float

    def line_of_sight(self) -> tuple[float, float, float]:
        """Unit vector from the receiver to the satellite in local east, north, up."""
        elevation = math.radians(self.elevation)
        azimuth = math.radians(self.azimuth)
        horizontal = math.cos(elevation)
        return (
            horizontal * math.sin(azimuth),
            horizontal * math.cos(azimuth),
            math.sin(elevation),
        )


@dataclass(frozen=True, slots=True)
class DilutionOfPrecision:
    """Geometric, position, horizontal, vertical and time dilution of precision."""

    gdop: float
    pdop: float
    hdop: float
    vdop: float
    tdop: float

    @classmethod
    def from_geometry(
        cls, satellites: Sequence[SatelliteGeometry]
    ) -> DilutionOfPrecision:
        """DOP from the covariance ``inverse(G^T G)`` of the ranging geometry."""
        covariance = invert(normal_matrix(design_matrix(satellites)))
        east, north, up, clock = (covariance[index][index] for index in range(4))
        return cls(
            gdop=math.sqrt(east + north + up + clock),
            pdop=math.sqrt(east + north + up),
            hdop=math.sqrt(east + north),
            vdop=math.sqrt(up),
            tdop=math.sqrt(clock),
        )


@dataclass(frozen=True, slots=True)
class ReportedDilution:
    """DOP values the receiver reports in a PSRDOP or RTKDOP frame."""

    source: str
    gdop: float
    pdop: float
    hdop: float
    tdop: float
    elevation_mask: float
    satellites: int

    @classmethod
    def from_record(cls, record: Record, source: str) -> ReportedDilution:
        """Read the receiver's own DOP, mask and satellite count from a frame."""
        return cls(
            source=record.name
            if source in ("PSRDOP", "RTKDOP") and record.name in ("SPPDOPH", "ADRDOPH")
            else source,
            gdop=record.real("gdop"),
            pdop=record.real("pdop"),
            hdop=record.real("hdop"),
            tdop=record.real("tdop"),
            elevation_mask=record.real("elev_mask"),
            satellites=record.integer("count_sats"),
        )


def geometry_from_record(
    record: Record, minimum_elevation: float = 0.0
) -> tuple[SatelliteGeometry, ...]:
    """Ranging geometry of the satellites of a decoded SATVIS2 frame."""
    kept = elevation_mask_filter(records_from(record, "satellites"), minimum_elevation)
    return tuple(
        SatelliteGeometry(
            azimuth=satellite.real("azimuth"), elevation=satellite.real("elevation")
        )
        for satellite in kept
    )


def geometry_from_records(
    records: Sequence[Record], minimum_elevation: float = 0.0
) -> tuple[SatelliteGeometry, ...]:
    """Ranging geometry across every constellation frame of one epoch."""
    return tuple(
        satellite
        for record in records
        for satellite in geometry_from_record(record, minimum_elevation)
    )


def design_row(satellite: SatelliteGeometry) -> tuple[float, float, float, float]:
    """One row of G: the negated unit line of sight and a unit clock coefficient."""
    east, north, up = satellite.line_of_sight()
    return (-east, -north, -up, 1.0)


def design_matrix(
    satellites: Sequence[SatelliteGeometry],
) -> tuple[tuple[float, float, float, float], ...]:
    """Design matrix G with one row per satellite."""
    return tuple(design_row(satellite) for satellite in satellites)


def normal_matrix(rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    """Normal matrix ``G^T G`` of a design matrix given as rows."""
    if not rows:
        raise ValueError("design matrix needs at least one row")
    columns = len(rows[0])
    return tuple(
        tuple(sum(row[i] * row[j] for row in rows) for j in range(columns))
        for i in range(columns)
    )


def invert(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    """Gauss-Jordan inverse with partial pivoting."""
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        raise ValueError("matrix must be square and nonempty")
    augmented = [
        [*map(float, row), *(1.0 if index == column else 0.0 for column in range(size))]
        for index, row in enumerate(matrix)
    ]
    for pivot in range(size):
        chosen = max(range(pivot, size), key=lambda row: abs(augmented[row][pivot]))
        if abs(augmented[chosen][pivot]) < 1e-12:
            raise ValueError("matrix is singular")
        augmented[pivot], augmented[chosen] = augmented[chosen], augmented[pivot]
        lead = augmented[pivot][pivot]
        augmented[pivot] = [value / lead for value in augmented[pivot]]
        for row in range(size):
            if row != pivot and augmented[row][pivot]:
                factor = augmented[row][pivot]
                augmented[row] = [
                    value - factor * lead_value
                    for value, lead_value in zip(
                        augmented[row], augmented[pivot], strict=True
                    )
                ]
    return tuple(tuple(row[size:]) for row in augmented)
