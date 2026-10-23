"""Counts per-constellation visibility and writes a sky-plot CSV."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from um982py.geodesy import elevation_mask_filter, records_from
from um982py.messages.record import Record, Value
from um982py.stats import mean, stddev


class Constellation(StrEnum):
    """Satellite navigation system reported by a SATVIS2 frame."""

    GPS = "GPS"
    GLONASS = "GLONASS"
    GALILEO = "GALILEO"
    BEIDOU = "BEIDOU"
    QZSS = "QZSS"
    SBAS = "SBAS"
    NAVIC = "NAVIC"

    @classmethod
    def from_value(cls, value: int | str) -> Constellation:
        """Name the system from an ASCII label or a binary system code."""
        if isinstance(value, str):
            return cls(value.strip().upper())
        try:
            return SYSTEM_CODES[value]
        except KeyError as error:
            raise ValueError(f"Unknown satellite system code: {value}") from error


SYSTEM_CODES: Mapping[int, Constellation] = {
    0: Constellation.GPS,
    1: Constellation.GLONASS,
    2: Constellation.SBAS,
    5: Constellation.GALILEO,
    6: Constellation.BEIDOU,
    7: Constellation.QZSS,
    9: Constellation.NAVIC,
}


@dataclass(frozen=True, slots=True)
class SkySatellite:
    """One visibility entry: angles in degrees, neutral ``field_7`` in dB-Hz."""

    constellation: Constellation
    prn: int
    channel: int
    elevation: float
    azimuth: float
    field_7: float


@dataclass(frozen=True, slots=True)
class AngleRange:
    """Minimum and maximum angles in degrees, or ``nan`` for an empty series."""

    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class FieldStatistics:
    """Mean, extremes and sample deviation of the neutral ``field_7`` values."""

    mean: float
    minimum: float
    maximum: float
    standard_deviation: float


@dataclass(frozen=True, slots=True)
class ConstellationVisibility:
    """Visibility summary of one constellation in one SATVIS2 frame."""

    constellation: Constellation
    count: int
    elevation: AngleRange
    azimuth: AngleRange
    field_7: FieldStatistics
    satellites: tuple[SkySatellite, ...]


def constellation_of(record: Record) -> Constellation:
    """Constellation of a SATVIS2 frame, from its ASCII or binary field."""
    value: Value = record["constellation"]
    if not isinstance(value, (int, str)):
        raise TypeError("constellation is not an integer or a string")
    return Constellation.from_value(value)


def sky_satellites(
    record: Record, minimum_elevation: float = 0.0
) -> tuple[SkySatellite, ...]:
    """Entries of one SATVIS2 frame at or above the elevation mask in degrees."""
    constellation = constellation_of(record)
    kept = elevation_mask_filter(records_from(record, "satellites"), minimum_elevation)
    return tuple(
        SkySatellite(
            constellation=constellation,
            prn=satellite.integer("prn"),
            channel=satellite.integer("channel"),
            elevation=satellite.real("elevation"),
            azimuth=satellite.real("azimuth"),
            field_7=satellite.real("field_7"),
        )
        for satellite in kept
    )


def visibility(
    record: Record, minimum_elevation: float = 0.0
) -> ConstellationVisibility:
    """Summarise the satellites of one SATVIS2 frame."""
    satellites = sky_satellites(record, minimum_elevation)
    elevations = [satellite.elevation for satellite in satellites]
    azimuths = [satellite.azimuth for satellite in satellites]
    values = [satellite.field_7 for satellite in satellites]
    return ConstellationVisibility(
        constellation=constellation_of(record),
        count=len(satellites),
        elevation=AngleRange(_minimum(elevations), _maximum(elevations)),
        azimuth=AngleRange(_minimum(azimuths), _maximum(azimuths)),
        field_7=FieldStatistics(
            mean=mean(values),
            minimum=_minimum(values),
            maximum=_maximum(values),
            standard_deviation=stddev(values),
        ),
        satellites=satellites,
    )


def visibility_summary(
    records: Sequence[Record], minimum_elevation: float = 0.0
) -> tuple[ConstellationVisibility, ...]:
    """Summarise one SATVIS2 frame per constellation, in frame order."""
    return tuple(visibility(record, minimum_elevation) for record in records)


def latest_frames(records: Sequence[Record]) -> tuple[Record, ...]:
    """Keep the last frame seen for each constellation, in first-seen order."""
    latest: dict[Constellation, Record] = {}
    for record in records:
        latest[constellation_of(record)] = record
    return tuple(latest.values())


def sky_plot_csv(satellites: Iterable[SkySatellite]) -> str:
    """Sky-plot rows of azimuth, elevation and prn as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("azimuth", "elevation", "prn"))
    for satellite in sorted(
        satellites, key=lambda item: (item.constellation.value, item.prn)
    ):
        writer.writerow(
            (f"{satellite.azimuth:.4f}", f"{satellite.elevation:.4f}", satellite.prn)
        )
    return buffer.getvalue()


def _minimum(values: list[float]) -> float:
    return min(values) if values else math.nan


def _maximum(values: list[float]) -> float:
    return max(values) if values else math.nan
