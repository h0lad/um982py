"""RANGE tracking identifiers from Unicore N4 R1.4 table 7-55."""

from dataclasses import dataclass

from um982py.gnss import (
    F_B1I,
    F_B3I,
    F_E5B,
    F_E6,
    F_G1,
    F_G1_STEP,
    F_G2,
    F_G2_STEP,
    F_G3,
    F_L1,
    F_L2,
    F_L5,
)
from um982py.messages.enums import SatelliteSystem

__all__ = ["TrackingSignal", "tracking_signal"]


@dataclass(frozen=True, slots=True)
class TrackingSignal:
    system: int
    signal: int
    constellation: str
    name: str
    rinex_code: str
    frequency_hz: float | None


_SIGNALS: dict[tuple[int, int], tuple[str, str, float | None]] = {
    (0, 0): ("L1 C/A", "1C", F_L1),
    (0, 3): ("L1C pilot", "1L", F_L1),
    (0, 11): ("L1C data", "1S", F_L1),
    (0, 9): ("L2 P(Y)", "2W", F_L2),
    (0, 17): ("L2C L", "2L", F_L2),
    (0, 6): ("L5 data", "5I", F_L5),
    (0, 14): ("L5 pilot", "5Q", F_L5),
    (1, 0): ("G1 C/A", "1C", None),
    (1, 5): ("G2 C/A", "2C", None),
    (1, 6): ("G3 I", "3I", F_G3),
    (1, 7): ("G3 Q", "3Q", F_G3),
    (2, 0): ("L1 C/A", "1C", F_L1),
    (3, 1): ("E1 B", "1B", F_L1),
    (3, 2): ("E1 C", "1C", F_L1),
    (3, 12): ("E5a pilot", "5Q", F_L5),
    (3, 17): ("E5b pilot", "7Q", F_E5B),
    (3, 18): ("E6 B", "6B", F_E6),
    (3, 22): ("E6 C", "6C", F_E6),
    (4, 0): ("B1 I", "2I", F_B1I),
    (4, 4): ("B1 Q", "2Q", F_B1I),
    (4, 8): ("B1C pilot", "1P", F_L1),
    (4, 23): ("B1C data", "1D", F_L1),
    (4, 5): ("B2 Q", "7Q", F_E5B),
    (4, 17): ("B2 I", "7I", F_E5B),
    (4, 12): ("B2a pilot", "5P", F_L5),
    (4, 28): ("B2a data", "5D", F_L5),
    (4, 6): ("B3 Q", "6Q", F_B3I),
    (4, 21): ("B3 I", "6I", F_B3I),
    (4, 13): ("B2b I", "7D", F_E5B),
    (5, 0): ("L1 C/A or L1C/B", "", F_L1),
    (5, 3): ("L1C pilot", "1L", F_L1),
    (5, 11): ("L1C data", "1S", F_L1),
    (5, 9): ("L2 P(Y)", "2X", F_L2),
    (5, 17): ("L2C L", "2L", F_L2),
    (5, 6): ("L5 data", "5I", F_L5),
    (5, 14): ("L5 pilot", "5Q", F_L5),
    (5, 21): ("L6 D", "6S", F_E6),
    (5, 27): ("L6 E", "6L", F_E6),
    (6, 6): ("L5 data", "5A", F_L5),
    (6, 14): ("L5 pilot", "5C", F_L5),
}
_L2C_COMPONENT_BIT = 1 << 26


def tracking_signal(
    status: int,
    *,
    glonass_channel: int | None = None,
    l2c_code: str | None = None,
) -> TrackingSignal | None:
    """Identify a tracking signal and its frequency.

    Type-9 L2C has an empty RINEX code unless the caller supplies its component.
    """
    if not 0 <= status <= 0xFFFFFFFF:
        raise ValueError("tracking status must be a u32")
    if l2c_code not in (None, "2S", "2L", "2X", "omit"):
        raise ValueError("l2c_code must be 2S, 2L, 2X, omit or None")
    if glonass_channel is not None and not -7 <= glonass_channel <= 6:
        raise ValueError("GLONASS FDMA channel must be in -7..6")
    system, signal = (status >> 16) & 7, (status >> 21) & 31
    definition = _SIGNALS.get((system, signal))
    if definition is None:
        return None
    name, code, hz = definition
    if system in (0, 5) and signal == 9 and status & _L2C_COMPONENT_BIT:
        name = "L2C (component unspecified)"
        code = "" if l2c_code in (None, "omit") else l2c_code
    if system == 5 and signal == 9 and not status & _L2C_COMPONENT_BIT:
        code = ""
    if system == 6 and signal == 14:
        code = ""
    if system == 1 and signal in (0, 5) and glonass_channel is not None:
        hz = (
            F_G1 + F_G1_STEP * glonass_channel
            if signal == 0
            else F_G2 + F_G2_STEP * glonass_channel
        )
    return TrackingSignal(
        system,
        signal,
        SatelliteSystem(system).name,
        name,
        code,
        hz,
    )
