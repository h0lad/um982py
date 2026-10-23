"""RANGE tracking identifiers from Unicore N4 R1.4 table 7-55."""

from dataclasses import dataclass

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
    (0, 0): ("L1 C/A", "1C", 1575.42),
    (0, 3): ("L1C pilot", "1L", 1575.42),
    (0, 11): ("L1C data", "1S", 1575.42),
    (0, 9): ("L2 P(Y)", "2W", 1227.60),
    (0, 17): ("L2C L", "2L", 1227.60),
    (0, 6): ("L5 data", "5I", 1176.45),
    (0, 14): ("L5 pilot", "5Q", 1176.45),
    (1, 0): ("G1 C/A", "1C", None),
    (1, 5): ("G2 C/A", "2C", None),
    (1, 6): ("G3 I", "3I", 1202.025),
    (1, 7): ("G3 Q", "3Q", 1202.025),
    (2, 0): ("L1 C/A", "1C", 1575.42),
    (3, 1): ("E1 B", "1B", 1575.42),
    (3, 2): ("E1 C", "1C", 1575.42),
    (3, 12): ("E5a pilot", "5Q", 1176.45),
    (3, 17): ("E5b pilot", "7Q", 1207.14),
    (3, 18): ("E6 B", "6B", 1278.75),
    (3, 22): ("E6 C", "6C", 1278.75),
    (4, 0): ("B1 I", "2I", 1561.098),
    (4, 4): ("B1 Q", "2Q", 1561.098),
    (4, 8): ("B1C pilot", "1P", 1575.42),
    (4, 23): ("B1C data", "1D", 1575.42),
    (4, 5): ("B2 Q", "7Q", 1207.14),
    (4, 17): ("B2 I", "7I", 1207.14),
    (4, 12): ("B2a pilot", "5P", 1176.45),
    (4, 28): ("B2a data", "5D", 1176.45),
    (4, 6): ("B3 Q", "6Q", 1268.52),
    (4, 21): ("B3 I", "6I", 1268.52),
    (4, 13): ("B2b I", "7D", 1207.14),
    (5, 0): ("L1 C/A or L1C/B", "", 1575.42),
    (5, 3): ("L1C pilot", "1L", 1575.42),
    (5, 11): ("L1C data", "1S", 1575.42),
    (5, 9): ("L2 P(Y)", "2X", 1227.60),
    (5, 17): ("L2C L", "2L", 1227.60),
    (5, 6): ("L5 data", "5I", 1176.45),
    (5, 14): ("L5 pilot", "5Q", 1176.45),
    (5, 21): ("L6 D", "6S", 1278.75),
    (5, 27): ("L6 E", "6L", 1278.75),
    (6, 6): ("L5 data", "5A", 1176.45),
    (6, 14): ("L5 pilot", "5C", 1176.45),
}
_SYSTEMS = ("GPS", "GLONASS", "SBAS", "GALILEO", "BEIDOU", "QZSS", "NAVIC")
_L2C_COMPONENT_BIT = 1 << 26


def tracking_signal(
    status: int,
    *,
    glonass_channel: int | None = None,
    l2c_code: str | None = None,
) -> TrackingSignal | None:
    """Identify a signal and leave unknown identifiers unknown."""
    if not 0 <= status <= 0xFFFFFFFF:
        raise ValueError("tracking status must be a u32")
    if l2c_code not in (None, "2S", "2L", "2X"):
        raise ValueError("l2c_code must be 2S, 2L, 2X or None")
    if glonass_channel is not None and not -7 <= glonass_channel <= 6:
        raise ValueError("GLONASS FDMA channel must be in -7..6")
    system, signal = (status >> 16) & 7, (status >> 21) & 31
    definition = _SIGNALS.get((system, signal))
    if definition is None:
        return None
    name, code, mhz = definition
    if system in (0, 5) and signal == 9 and status & _L2C_COMPONENT_BIT:
        name, code = "L2C (component unspecified)", l2c_code or ""
    if system == 5 and signal == 9 and not status & _L2C_COMPONENT_BIT:
        code = ""
    if system == 6 and signal == 14:
        code = ""
    if system == 1 and signal in (0, 5) and glonass_channel is not None:
        mhz = (
            (1602.0 + 0.5625 * glonass_channel)
            if signal == 0
            else (1246.0 + 0.4375 * glonass_channel)
        )
    return TrackingSignal(
        system,
        signal,
        _SYSTEMS[system],
        name,
        code,
        None if mhz is None else mhz * 1_000_000,
    )
