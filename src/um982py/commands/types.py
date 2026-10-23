"""The enumerations shared by command builders."""

from enum import StrEnum


class Port(StrEnum):
    COM1 = "COM1"
    COM2 = "COM2"
    COM3 = "COM3"


class Parity(StrEnum):
    NONE = "N"
    EVEN = "E"
    ODD = "O"


class Trigger(StrEnum):
    ON_CHANGED = "ONCHANGED"


class NmeaVersion(StrEnum):
    V410 = "V410"
    V411 = "V411"


class RoverDynamics(StrEnum):
    SURVEY = "SURVEY"
    UAV = "UAV"
    AUTOMOTIVE = "AUTOMOTIVE"
    RACING = "RACING"


class Constellation(StrEnum):
    GPS = "GPS"
    BDS = "BDS"
    GLONASS = "GLO"
    GALILEO = "GAL"
    QZSS = "QZSS"
    NAVIC = "IRNSS"
    SBAS = "SBAS"


class ResetTarget(StrEnum):
    EPHEMERIS = "EPHEM"
    CONFIGURATION = "CONFIG"
    IONOSPHERE_UTC = "IONUTC"
    ALMANAC = "ALMANAC"
    POSITION = "POSITION"
    OSCILLATOR = "XOPARAM"
    CLOCK_DRIFT = "CLOCKDRIFT"
    ALL = "ALL"
