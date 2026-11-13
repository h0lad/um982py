"""Receiver-reported position uncertainty and GST error ellipses."""

import math
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from um982py.messages.record import Record, Value


def utc_seconds(value: str) -> Decimal:
    """Parse a GGA/GST UTC time of day without inventing a date."""
    if re.fullmatch(r"[0-9]{6}(?:\.[0-9]+)?", value) is None:
        raise ValueError("UTC time must use hhmmss[.fraction]")
    hour, minute, second = int(value[:2]), int(value[2:4]), Decimal(value[4:])
    if hour >= 24 or minute >= 60 or second >= 60:
        raise ValueError("UTC time is out of range")
    return Decimal(hour * 3600 + minute * 60) + second


def _nonnegative(value: Value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


@dataclass(frozen=True, slots=True)
class ErrorEllipse:
    """Receiver-reported one-sigma horizontal ellipse, oriented from true north."""

    semi_major_m: float
    semi_minor_m: float
    orientation_deg: float

    def __post_init__(self) -> None:
        if (
            not all(
                not isinstance(value, bool) and math.isfinite(value)
                for value in (
                    self.semi_major_m,
                    self.semi_minor_m,
                    self.orientation_deg,
                )
            )
            or self.semi_minor_m < 0
            or self.semi_major_m < self.semi_minor_m
            or not 0 <= self.orientation_deg <= 360
        ):
            raise ValueError("invalid receiver error ellipse")


@dataclass(frozen=True, slots=True)
class PositionPrecision:
    """Estimated one-sigma deviations in local east, north and up metres.

    Unknown values remain None. An ellipse is reported only when the receiver
    supplied it; no correlation or confidence level is inferred. UTC is time
    of day without a date. These are receiver estimates, not accuracy bounds.
    """

    source: str
    east_std_m: float | None = None
    north_std_m: float | None = None
    up_std_m: float | None = None
    ellipse: ErrorEllipse | None = None
    epoch_gps_seconds: float | None = None
    utc: str | None = None
    antenna: int | None = None
    pseudorange_rms_m: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("precision source is required")
        for value in (
            self.east_std_m,
            self.north_std_m,
            self.up_std_m,
            self.pseudorange_rms_m,
        ):
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("precision values must be finite and non-negative")
        if self.epoch_gps_seconds is not None and (
            isinstance(self.epoch_gps_seconds, bool)
            or not math.isfinite(self.epoch_gps_seconds)
        ):
            raise ValueError("precision epoch must be finite")
        if self.utc is not None:
            utc_seconds(self.utc)
        if self.antenna is not None and (
            type(self.antenna) is not int or self.antenna not in (1, 2)
        ):
            raise ValueError("precision antenna must be 1 or 2")

    @property
    def available(self) -> bool:
        """Whether a position deviation or ellipse is available."""
        return self.ellipse is not None or any(
            value is not None
            for value in (self.east_std_m, self.north_std_m, self.up_std_m)
        )

    @property
    def horizontal_rms_m(self) -> float | None:
        """Root-sum-square of axis deviations, not a confidence radius."""
        if self.east_std_m is None or self.north_std_m is None:
            return None
        value = math.hypot(self.east_std_m, self.north_std_m)
        return value if math.isfinite(value) else None

    def as_dict(self) -> dict[str, Any]:
        """Return map-friendly receiver estimates, preserving unknowns as None."""
        return {**asdict(self), "horizontal_rms_m": self.horizontal_rms_m}

    @classmethod
    def from_gst(cls, record: Record) -> "PositionPrecision":
        """Interpret a decoded GST/GSTH record without attaching it to a fix."""
        kind = record.name[2:]
        if kind not in ("GST", "GSTH"):
            raise ValueError("expected a GST or GSTH record")
        utc = record.get("utc")
        if not isinstance(utc, str):
            raise ValueError("GST requires a UTC time of day")
        utc_seconds(utc)
        major = _nonnegative(record.get("semi_major"))
        minor = _nonnegative(record.get("semi_minor"))
        orientation = _nonnegative(record.get("orientation"))
        ellipse = None
        if major is not None and minor is not None and orientation is not None:
            ellipse = ErrorEllipse(major, minor, orientation)
        return cls(
            source=record.name,
            east_std_m=_nonnegative(record.get("longitude_std")),
            north_std_m=_nonnegative(record.get("latitude_std")),
            up_std_m=_nonnegative(record.get("altitude_std")),
            ellipse=ellipse,
            utc=utc,
            antenna=2 if kind == "GSTH" else 1,
            pseudorange_rms_m=_nonnegative(record.get("rms")),
        )
