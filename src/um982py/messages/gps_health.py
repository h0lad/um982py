"""GPS LNAV health interpretation, IS-GPS-200N sections 20.3.3.3 and 20.3.3.5."""

from dataclasses import dataclass

from um982py.messages.enums import MessageSatelliteSystem
from um982py.messages.record import Record

# IS-GPS-200N table 20-VIII: five-bit signal-component status, not a bitmask.
_SIGNAL_STATUS = (
    "all signals OK",
    "all signals weak",
    "all signals dead",
    "all signals have no data modulation",
    "L1 P signal weak",
    "L1 P signal dead",
    "L1 P signal has no data modulation",
    "L2 P signal weak",
    "L2 P signal dead",
    "L2 P signal has no data modulation",
    "L1 C signal weak",
    "L1 C signal dead",
    "L1 C signal has no data modulation",
    "L2 C signal weak",
    "L2 C signal dead",
    "L2 C signal has no data modulation",
    "L1 and L2 P signals weak",
    "L1 and L2 P signals dead",
    "L1 and L2 P signals have no data modulation",
    "L1 and L2 C signals weak",
    "L1 and L2 C signals dead",
    "L1 and L2 C signals have no data modulation",
    "L1 signal weak",
    "L1 signal dead",
    "L1 signal has no data modulation",
    "L2 signal weak",
    "L2 signal dead",
    "L2 signal has no data modulation",
    "satellite temporarily out",
    "satellite will be temporarily out",
    "one or more signals deformed; URA valid",
    "multiple signal anomalies",
)


@dataclass(frozen=True, slots=True)
class GpsLnavHealth:
    """Broadcast subframe-1 health, not a measurement of current satellite state."""

    prn: int
    raw: int

    def __post_init__(self) -> None:
        if not 1 <= self.prn <= 32:
            raise ValueError("GPSEPH PRN is not a GPS satellite")
        if not 0 <= self.raw <= 63:
            raise ValueError("GPS LNAV health must be a six-bit value")

    @property
    def navigation_data_ok(self) -> bool:
        """False means some or all navigation data are bad."""
        return not bool(self.raw & 0x20)

    @property
    def signal_status_code(self) -> int:
        return self.raw & 0x1F

    @property
    def signal_status(self) -> str:
        return _SIGNAL_STATUS[self.signal_status_code]

    @classmethod
    def from_record(cls, record: Record) -> "GpsLnavHealth":
        """Interpret the transmitting satellite's GPSEPH health."""
        if record.name != "GPSEPH":
            raise ValueError("expected a GPSEPH record")
        prn = record.integer("prn")
        raw = record.integer("health")
        return cls(prn, raw)


def gps_visible_health(record: Record) -> tuple[tuple[int, bool | None], ...]:
    """Return (PRN, health) for entries in a GPS SATELLITE record.

    True means receiver-reported healthy, False means unhealthy, and None
    represents an undocumented value, and missing satellites are not inferred.
    """
    if record.name != "SATELLITE":
        raise ValueError("expected a SATELLITE record")
    system = record["satellite_system"]
    if (
        not isinstance(system, (int, str))
        or MessageSatelliteSystem.from_wire(system) != MessageSatelliteSystem.GPS
    ):
        raise ValueError("expected a GPS SATELLITE record")
    result = []
    for sat in record.records("satellites"):
        satellite_id = sat["prn_slot"]
        if not isinstance(satellite_id, Record):
            raise TypeError("prn_slot is not a satellite ID")
        result.append(
            (
                satellite_id.integer("prn"),
                {0: True, 1: False}.get(sat.integer("health")),
            )
        )
    return tuple(result)
