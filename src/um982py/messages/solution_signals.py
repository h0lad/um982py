"""Signals used by a position solution, from R1.15 tables 7-177 and 7-178."""

from dataclasses import dataclass
from enum import IntFlag

from um982py.messages.record import Record


class GalileoBds3Signals(IntFlag):
    GALILEO_E1 = 0x01
    GALILEO_E5B = 0x02
    GALILEO_E5A = 0x04
    BDS3_B1I = 0x10
    BDS3_B3I = 0x20
    BDS3_B2A = 0x40
    BDS3_B1C = 0x80


class GpsGlonassBds2Signals(IntFlag):
    GPS_L1 = 0x01
    GPS_L2 = 0x02
    GPS_L5 = 0x04
    BDS_B3I = 0x08
    GLONASS_L1 = 0x10
    GLONASS_L2 = 0x20
    BDS_B1I = 0x40
    BDS2_B2I = 0x80


@dataclass(frozen=True, slots=True)
class SolutionSignals:
    """Receiver-reported solution signal masks retain reserved bits in the value.

    These flags report signal use, not correction application or solution accuracy.
    """

    galileo_bds3: GalileoBds3Signals
    gps_glonass_bds2: GpsGlonassBds2Signals

    @classmethod
    def from_record(cls, record: Record) -> "SolutionSignals":
        """Read the named masks from a decoded navigation solution record."""
        galileo = record.integer("galileo_bds3_sig_mask")
        other = record.integer("gps_glonass_and_bds2_sig_mask")
        if not 0 <= galileo <= 255 or not 0 <= other <= 255:
            raise ValueError("solution signal masks must be unsigned bytes")
        return cls(GalileoBds3Signals(galileo), GpsGlonassBds2Signals(other))
