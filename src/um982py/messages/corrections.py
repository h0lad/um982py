"""HAS correction value types and helpers."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DO_NOT_USE = "do_not_use"


@dataclass(frozen=True, slots=True)
class Correction:
    raw: int
    meters: float | None
    availability: Availability


VALIDITY_SECONDS = (
    5,
    10,
    15,
    20,
    30,
    60,
    90,
    120,
    180,
    240,
    300,
    600,
    900,
    1800,
    3600,
    None,
)
FORMATS = {
    "radial": (13, 0.0025),
    "in_track": (12, 0.008),
    "cross_track": (12, 0.008),
    "clock": (13, 0.0025),
    "code": (11, 0.0025),
    "phase": (11, 0.01),
}


# HAS signal indices use their own GNSS numbering, distinct from RANGE status
# and NMEA signal identifiers. R1.15 table 7-191 uses GNSS 0=GPS, 2=Galileo.
HAS_SIGNALS: dict[int, tuple[str | None, ...]] = {
    0: (
        "L1 C/A",
        None,
        None,
        "L1C(D)",
        "L1C(P)",
        "L1C(D+P)",
        "L2 CM",
        "L2 CL",
        "L2 CM+CL",
        "L2 P",
        None,
        "L5 I",
        "L5 Q",
        "L5 I+Q",
        None,
        None,
    ),
    2: (
        "E1-B I/NAV OS",
        "E1-C",
        "E1-B+E1-C",
        "E5a-I F/NAV OS",
        "E5a-Q",
        "E5a-I+Q",
        "E5b-I I/NAV OS",
        "E5b-Q",
        "E5b-I+Q",
        "E5-I",
        "E5-Q",
        "E5-I+Q",
        "E6-B C/NAV HAS",
        "E6-C",
        "E6-B+E6-C",
        None,
    ),
}


def has_correction(
    raw: int,
    kind: Literal["radial", "in_track", "cross_track", "clock", "code", "phase"],
    *,
    multiplier: Literal[1, 2, 3, 4] = 1,
) -> Correction:
    bits, scale = FORMATS[kind]
    if type(raw) is not int or not -(1 << (bits - 1)) <= raw < 1 << (bits - 1):
        raise ValueError("HAS correction is outside its signed field range")
    if type(multiplier) is not int or multiplier not in (1, 2, 3, 4):
        raise ValueError("Delta clock multiplier must be 1..4")
    if kind != "clock" and multiplier != 1:
        raise ValueError("Multiplier applies only to delta clock corrections")
    if raw == -(1 << (bits - 1)):
        return Correction(raw, None, Availability.UNAVAILABLE)
    if kind == "clock" and raw == (1 << (bits - 1)) - 1:
        return Correction(raw, None, Availability.DO_NOT_USE)
    return Correction(raw, raw * scale * multiplier, Availability.AVAILABLE)


def has_validity_seconds(index: int) -> int | None:
    if type(index) is not int or not 0 <= index < len(VALIDITY_SECONDS):
        raise ValueError("HAS validity index must be 0..15")
    return VALIDITY_SECONDS[index]


def has_clock_multiplier(encoded: int) -> Literal[1, 2, 3, 4]:
    """Convert the R1.15 two-bit clock multiplier to a scale factor."""
    if type(encoded) is not int or not 0 <= encoded <= 3:
        raise ValueError("HAS clock multiplier code must be an integer in 0..3")
    return (1, 2, 3, 4)[encoded]


def mask_indices(mask: bytes) -> tuple[int, ...]:
    return tuple(
        index
        for index in range(len(mask) * 8)
        if mask[index // 8] & (1 << (7 - index % 8))
    )


def has_signal_indices(signal_mask: int) -> tuple[int, ...]:
    """Return the set signal indices of a 16-bit Galileo HAS signal mask."""
    if type(signal_mask) is not int or not 0 <= signal_mask <= 0xFFFF:
        raise ValueError("HAS signal mask must be a 16-bit unsigned integer")
    return mask_indices(signal_mask.to_bytes(2, "big"))


def has_signal_name(gnss_id: int, signal_index: int) -> str | None:
    """Return the R1.15 HAS signal name, or None for a reserved identifier."""
    if type(gnss_id) is not int or not 0 <= gnss_id <= 15:
        raise ValueError("HAS GNSS ID must be in 0..15")
    if type(signal_index) is not int or not 0 <= signal_index <= 15:
        raise ValueError("HAS signal index must be in 0..15")
    signals = HAS_SIGNALS.get(gnss_id)
    return None if signals is None else signals[signal_index]
