"""Validated baseband PVT solutions and their cross-family agreement."""

from dataclasses import dataclass
from math import dist, isfinite
from typing import Self

from um982py.errors import ProtocolError
from um982py.geodesy import ecef_from_geodetic
from um982py.messages.record import Record

__all__ = [
    "BasebandSolution",
    "solution_jump_m",
    "solution_separation_m",
]


def _real_value(record: Record, key: str) -> float:
    value = record[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{record.name} has no numeric {key}")
    if not isfinite(value):
        raise ProtocolError(f"{record.name} has a non-finite {key}")
    return float(value)


@dataclass(frozen=True, slots=True)
class BasebandSolution:
    """One baseband position line with its printed-ECEF agreement residual."""

    tag: int
    latitude: float
    longitude: float
    height: float
    x: float
    y: float
    z: float
    ecef_residual_m: float

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Validate one decoded NAVPOS record against its own ECEF triple."""
        if record.name != "NAVPOS":
            raise ProtocolError(f"Expected a NAVPOS record, got {record.name}")
        tag = record["tag"]
        if not isinstance(tag, int):
            raise ProtocolError("NAVPOS tag is not an integer")
        latitude = _real_value(record, "latitude")
        longitude = _real_value(record, "longitude")
        height = _real_value(record, "height")
        x = _real_value(record, "x")
        y = _real_value(record, "y")
        z = _real_value(record, "z")
        projected = ecef_from_geodetic(latitude, longitude, height)
        residual = max(
            abs(projected[axis] - value) for axis, value in enumerate((x, y, z))
        )
        return cls(tag, latitude, longitude, height, x, y, z, residual)


def solution_separation_m(position: Record, result: Record) -> float:
    """Return the ECEF distance between a NAVPOS and a POS_RESULT record."""
    if position.name != "NAVPOS" or result.name != "POS_RESULT":
        raise ProtocolError("Expected NAVPOS and POS_RESULT records")
    return dist(
        (
            _real_value(position, "x"),
            _real_value(position, "y"),
            _real_value(position, "z"),
        ),
        (
            _real_value(result, "x"),
            _real_value(result, "y"),
            _real_value(result, "z"),
        ),
    )


def solution_jump_m(previous: BasebandSolution, current: BasebandSolution) -> float:
    """Return the ECEF distance between two validated baseband solutions."""
    return dist(
        (previous.x, previous.y, previous.z),
        (current.x, current.y, current.z),
    )
