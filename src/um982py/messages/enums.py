from collections.abc import Mapping
from enum import IntEnum, IntFlag, StrEnum
from types import MappingProxyType
from typing import override


def _reported_datum[T](value: T) -> T | str:
    """Name the documented WGS84 datum code and preserve other values."""
    return "WGS84" if type(value) is int and value == 61 else value


def enum_member[E: IntEnum](enum: type[E], value: object) -> E | None:
    """Find an enum member by numeric code or ASCII label, or return None."""
    try:
        if isinstance(value, str):
            return enum[value]
        if isinstance(value, int) and not isinstance(value, bool):
            return enum(value)
    except KeyError, ValueError:
        pass
    return None


def enum_or_raw[E: IntEnum, V](enum: type[E], value: V) -> E | V:
    """Return the enum member for a code or label, keeping unknown values."""
    member = enum_member(enum, value)
    return value if member is None else member


_POSITION_TYPE_LABELS: dict[int, str] = {
    0: "none",
    1: "fixed position",
    2: "fixed height",
    8: "Doppler velocity",
    16: "SINGLE",
    17: "PSRDIFF",
    18: "SBAS",
    32: "L1_FLOAT",
    33: "IONO_FREE_FLOAT",
    34: "NARROW_FLOAT",
    48: "L1_INT",
    49: "WIDE_INT",
    50: "NARROW_INT",
    52: "INS",
    53: "INS_PSRSP",
    54: "INS_PSRDIFF",
    55: "INS_RTKFLOAT",
    56: "INS_RTKFIXED",
    68: "PPP_CONVERGING",
    69: "PPP",
    70: "PPP_AR",
    71: "PPP_RTK",
}


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

    @override
    def __str__(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        """Return the documented position type name used in reports."""
        return _POSITION_TYPE_LABELS.get(int(self), self.name)

    @property
    def is_ppp(self) -> bool:
        """Whether this is one of the receiver's PPP position types."""
        return self in _PPP or self is PositionType.PPP_CONVERGING

    @property
    def is_ppp_converged(self) -> bool:
        """Whether this is a PPP position type beyond convergence."""
        return self in _PPP

    @property
    def is_rtk_fixed(self) -> bool:
        """Whether carrier ambiguities are fixed by RTK, with or without INS."""
        return self in _RTK_FIXED

    @property
    def is_rtk_float(self) -> bool:
        """Whether this is a float-ambiguity RTK type, with or without INS."""
        return self in _RTK_FLOAT

    @property
    def is_differential(self) -> bool:
        """Whether the position depends on differential base corrections."""
        return self in _DIFFERENTIAL

    @property
    def fix_class(self) -> FixClass | None:
        """Return the solution category, or None for unclassified types."""
        return POSITION_CLASSES.get(self)


class FixClass(StrEnum):
    """Solution categories shared by position types and GGA quality codes."""

    FIXED = "fixed"
    FLOAT = "float"
    PPP = "ppp"
    PPP_CONVERGING = "ppp_converging"
    SINGLE = "single"
    NONE = "none"


POSITION_CLASSES: Mapping[PositionType, FixClass] = MappingProxyType(
    {
        PositionType.NONE: FixClass.NONE,
        PositionType.FIXEDPOS: FixClass.SINGLE,
        PositionType.FIXEDHEIGHT: FixClass.SINGLE,
        PositionType.SINGLE: FixClass.SINGLE,
        PositionType.PSRDIFF: FixClass.SINGLE,
        PositionType.SBAS: FixClass.SINGLE,
        PositionType.L1_FLOAT: FixClass.FLOAT,
        PositionType.IONOFREE_FLOAT: FixClass.FLOAT,
        PositionType.NARROW_FLOAT: FixClass.FLOAT,
        PositionType.L1_INT: FixClass.FIXED,
        PositionType.WIDE_INT: FixClass.FIXED,
        PositionType.NARROW_INT: FixClass.FIXED,
        PositionType.INS_PSRSP: FixClass.SINGLE,
        PositionType.INS_PSRDIFF: FixClass.SINGLE,
        PositionType.INS_RTKFLOAT: FixClass.FLOAT,
        PositionType.INS_RTKFIXED: FixClass.FIXED,
        PositionType.PPP_CONVERGING: FixClass.PPP_CONVERGING,
        PositionType.PPP: FixClass.PPP,
        PositionType.PPP_AR: FixClass.PPP,
        PositionType.PPP_RTK: FixClass.PPP,
    }
)


_PPP = frozenset((PositionType.PPP, PositionType.PPP_AR, PositionType.PPP_RTK))
_RTK_FIXED = frozenset(
    (
        PositionType.L1_INT,
        PositionType.WIDE_INT,
        PositionType.NARROW_INT,
        PositionType.INS_RTKFIXED,
    )
)
_RTK_FLOAT = frozenset(
    (
        PositionType.L1_FLOAT,
        PositionType.IONOFREE_FLOAT,
        PositionType.NARROW_FLOAT,
        PositionType.INS_RTKFLOAT,
    )
)
_DIFFERENTIAL = frozenset(
    (PositionType.PSRDIFF, PositionType.INS_PSRDIFF, *_RTK_FIXED, *_RTK_FLOAT)
)


class SolutionStatus(IntEnum):
    SOL_COMPUTED = 0
    INSUFFICIENT_OBS = 1
    NO_CONVERGENCE = 2
    SINGULARITY = 3
    COV_TRACE = 4

    @override
    def __str__(self) -> str:
        return self.name


_RINEX_LETTERS = {
    "GPS": "G",
    "GLONASS": "R",
    "SBAS": "S",
    "GALILEO": "E",
    "BEIDOU": "C",
    "QZSS": "J",
    "NAVIC": "I",
}


class _Constellation:
    """Canonical constellation naming shared by the receiver's wire numberings.

    Member names are the library-wide constellation strings. NavIC replaces
    the former IRNSS name, as in RINEX 4.
    """

    __slots__ = ()
    name: str

    @property
    def rinex(self) -> str:
        """Return the RINEX satellite-system letter."""
        return _RINEX_LETTERS[self.name]


class SatelliteSystem(_Constellation, IntEnum):
    """Satellite system in RANGE/OBSV channel tracking status.

    ``IRNSS`` is an alias of ``NAVIC`` for the receiver's legacy label.
    """

    GPS = 0
    GLONASS = 1
    SBAS = 2
    GALILEO = 3
    BEIDOU = 4
    QZSS = 5
    NAVIC = 6
    IRNSS = 6


class MessageSatelliteSystem(_Constellation, IntEnum):
    """Satellite-system values from R1.15 table 7-175."""

    GPS = 0
    GLONASS = 1
    SBAS = 2
    GALILEO = 5
    BEIDOU = 6
    QZSS = 7
    NAVIC = 9

    @classmethod
    def from_wire(cls, value: int | str) -> MessageSatelliteSystem:
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
