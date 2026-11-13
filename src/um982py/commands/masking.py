"""Elevation, satellite and C/N0 mask commands."""

from um982py.commands.core import Command, action, number
from um982py.commands.types import Constellation
from um982py.commands.validation import integer, option
from um982py.messages import CommandResponse

FREQUENCIES = (
    "L1",
    "L1CA",
    "L1C",
    "L2",
    "L2C",
    "L2P",
    "L5",
    "B1",
    "B2",
    "B3",
    "B1I",
    "B2I",
    "B3I",
    "BD3B1C",
    "BD3B2A",
    "BD3B2B",
    "R1",
    "R2",
    "R3",
    "E1",
    "E5A",
    "E5B",
    "E6C",
    "Q1",
    "Q2",
    "Q5",
    "Q1CA",
    "Q1C",
    "Q2C",
    "I5",
)


def frequency(signal: str, *, enabled: bool = False) -> Command[CommandResponse]:
    """Mask or unmask a documented signal token.

    R1.16 notes that BeiDou-2 signals will no longer be tracked. B2I remains
    available here for receivers and firmware that support it.
    """
    return action(f"{'UNMASK' if enabled else 'MASK'} {option(signal, FREQUENCIES)}")


def satellite(
    system: Constellation, prn: int, *, enabled: bool = False
) -> Command[CommandResponse]:
    selected = Constellation(system)
    limits = {
        Constellation.GPS: (1, 32),
        Constellation.BDS: (1, 63),
        Constellation.GLONASS: (38, 61),
        Constellation.GALILEO: (1, 36),
        Constellation.QZSS: (193, 202),
        Constellation.NAVIC: (1, 15),
        Constellation.SBAS: (120, 158),
    }
    value = integer(prn, *limits[selected])
    verb = "UNMASK" if enabled else "MASK"
    return action(f"{verb} {selected.value} PRN {value}")


def cn0(
    threshold: float, *, signal: str | None = None, rtcm: bool = False
) -> Command[CommandResponse]:
    parts = ["MASK", "RTCMCN0" if rtcm else "CN0", number(threshold, 0, float("inf"))]
    if signal is not None:
        parts.append(option(signal, FREQUENCIES))
    return action(" ".join(parts))


def azimuth(
    elevation_min: float,
    elevation_max: float,
    azimuth_min: float,
    azimuth_max: float,
) -> Command[CommandResponse]:
    """Mask a sky sector using ordered elevation and azimuth bounds.

    Angles are degrees. Bounds must be ordered; sectors crossing north are
    not supported by this builder. Uses the ``MASK AZIMUTH 1`` command form.
    Receiver firmware determines availability of this mode.
    """
    elevations = [number(value, -90, 90) for value in (elevation_min, elevation_max)]
    azimuths = [number(value, 0, 360) for value in (azimuth_min, azimuth_max)]
    if elevation_min >= elevation_max or azimuth_min >= azimuth_max:
        raise ValueError("Sector minimum angles must be smaller than maximum angles")
    return action(" ".join(("MASK AZIMUTH 1", *elevations, *azimuths)))
