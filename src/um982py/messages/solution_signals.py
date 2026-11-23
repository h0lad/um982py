"""Signals used by a position solution, from R1.15 tables 7-177 and 7-178."""

from dataclasses import dataclass
from enum import IntFlag

from um982py.messages.enums import MessageSatelliteSystem
from um982py.messages.record import Record

_BESTSATS_BANDS = {
    MessageSatelliteSystem.GPS: {0x01: "L1", 0x02: "L2", 0x04: "L5"},
    MessageSatelliteSystem.GLONASS: {0x01: "G1", 0x02: "G2", 0x04: "G3"},
    MessageSatelliteSystem.GALILEO: {0x01: "E1", 0x02: "E5a", 0x04: "E5b", 0x20: "E6"},
    MessageSatelliteSystem.BEIDOU: {
        0x01: "B1I",
        0x02: "B2I",
        0x04: "B3I",
        0x08: "B1C",
        0x20: "B2a",
        0x40: "B2b",
    },
}


def bestsats_signal_bands(satellite: Record) -> tuple[str, ...]:
    """Return known bands for a GOOD satellite row from UM982 BESTSATS."""
    system = satellite.get("system")
    if satellite.get("state") not in (0, "GOOD") or not isinstance(system, (int, str)):
        return ()
    try:
        constellation = MessageSatelliteSystem.from_wire(system)
    except ValueError:
        return ()
    fields = _BESTSATS_BANDS.get(constellation, {})
    flags = satellite.integer("flags")
    return tuple(band for bit, band in fields.items() if flags & bit)


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
    """Signals reported by the receiver as used in a position solution.

    The masks retain reserved bits in their values.
    """

    galileo_bds3: GalileoBds3Signals
    gps_glonass_bds2: GpsGlonassBds2Signals

    @classmethod
    def from_record(cls, record: Record) -> "SolutionSignals":
        galileo = record.integer("galileo_bds3_sig_mask")
        other = record.integer("gps_glonass_and_bds2_sig_mask")
        if not 0 <= galileo <= 255 or not 0 <= other <= 255:
            raise ValueError("solution signal masks must be unsigned bytes")
        return cls(GalileoBds3Signals(galileo), GpsGlonassBds2Signals(other))
