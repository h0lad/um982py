"""Enumerations used by decoded messages."""

from enum import IntEnum, IntFlag


class PositionType(IntEnum):
    NONE = 0
    FIXEDPOS = 1
    FIXEDHEIGHT = 2
    DOPPLER_VELOCITY = 8
    SINGLE = 16
    PSRDIFF = 17
    SBAS = 18
    L1_FLOAT = 32
    IONOFREE_FLOAT = 33
    NARROW_FLOAT = 34
    L1_INT = 48
    WIDE_INT = 49
    NARROW_INT = 50
    INS = 52
    INS_PSRSP = 53
    INS_PSRDIFF = 54
    INS_RTKFLOAT = 55
    INS_RTKFIXED = 56
    PPP_CONVERGING = 68
    PPP = 69
    PPP_AR = 70
    PPP_RTK = 71


class SolutionStatus(IntEnum):
    SOL_COMPUTED = 0
    INSUFFICIENT_OBS = 1
    NO_CONVERGENCE = 2
    SINGULARITY = 3
    COV_TRACE = 4


class SatelliteSystem(IntEnum):
    """Satellite system in RANGE/OBSV channel tracking status."""

    GPS = 0
    GLONASS = 1
    SBAS = 2
    GALILEO = 3
    BEIDOU = 4
    QZSS = 5
    IRNSS = 6


class MessageSatelliteSystem(IntEnum):
    """Satellite-system values in R1.15 table 7-175, not tracking-status bits."""

    GPS = 0
    GLONASS = 1
    SBAS = 2
    GALILEO = 5
    BEIDOU = 6
    QZSS = 7
    NAVIC = 9

    @classmethod
    def from_wire(cls, value: int | str) -> "MessageSatelliteSystem":
        """Decode a binary value or the documented ASCII satellite-system name."""
        if isinstance(value, str):
            try:
                return cls[value]
            except KeyError:
                raise ValueError(f"Unknown satellite system: {value!r}") from None
        if type(value) is not int:
            raise ValueError("Satellite system must be an integer or ASCII name")
        return cls(value)


class EventStatus(IntFlag):
    SECONDS_VALID = 1
    PPS_VALID = 2
    WEEK_VALID = 8


class HardwareFlags(IntFlag):
    CRYSTAL = 1
    TCXO = 2
    OSCILLATOR_20_MHZ = 4
    OSCILLATOR_AND_CRYSTAL = 8
    EXTERNAL_CLOCK = 16
    VALID = 128


class HasBlocks(IntFlag):
    PHASE_BIAS = 1
    CODE_BIAS = 2
    CLOCK_SUBSET = 4
    CLOCK_FULL_SET = 8
    ORBIT = 16
    MASK = 32


class AssistedStatus(IntFlag):
    DATA_PRESENT = 1
    SUFFICIENT_SATELLITES = 2
    TIME_VALID = 4
    POSITION_VALID = 8
