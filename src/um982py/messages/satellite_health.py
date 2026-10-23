"""Interpret receiver ephemeris health without inferring unreported status."""
#  Sources: Unicore R1.15 BD3EPH, BDSEPH, GALEPH and GLOEPH log descriptions;
# Galileo OS SIS ICD 2.1 tables 79 and 82; BDS B1I SIS ICD section 5.2.4.6.

from dataclasses import dataclass
from enum import IntEnum

from um982py.messages.record import Record


class GalileoSignalHealth(IntEnum):
    OK = 0
    OUT_OF_SERVICE = 1
    EXTENDED_OPERATIONS = 2
    TEST = 3


class GalileoDataValidity(IntEnum):
    VALID = 0
    WITHOUT_GUARANTEE = 1


@dataclass(frozen=True, slots=True)
class GalileoSignalStatus:
    """Raw codes are retained even when the receiver says they are unavailable."""

    received: bool | None
    health_code: int | None
    data_validity_code: int | None

    @property
    def health(self) -> GalileoSignalHealth | None:
        if self.received is not True or self.health_code is None:
            return None
        try:
            return GalileoSignalHealth(self.health_code)
        except ValueError:
            return None

    @property
    def data_validity(self) -> GalileoDataValidity | None:
        if self.received is not True or self.data_validity_code is None:
            return None
        try:
            return GalileoDataValidity(self.data_validity_code)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class GalileoEphemerisHealth:
    satellite_id: int
    e1b: GalileoSignalStatus
    e5a: GalileoSignalStatus
    e5b: GalileoSignalStatus

    @classmethod
    def from_record(cls, record: Record) -> "GalileoEphemerisHealth":
        if record.name != "GALEPH":
            raise ValueError("expected a GALEPH record")

        def received(name: str) -> bool | None:
            value = record[name]
            if value == "TRUE" or value == 1:
                return True
            if value == "FALSE" or value == 0:
                return False
            return None

        fnav, inav = received("fnavreceived"), received("inavreceived")

        def signal(name: str, available: bool | None) -> GalileoSignalStatus:
            def code(key: str) -> int | None:
                value = record[key]
                if value is None:
                    return None
                return record.integer(key)

            return GalileoSignalStatus(
                available, code(name + "health"), code(name + "dvs")
            )

        return cls(
            record.integer("satid"),
            signal("e1b", inav),
            signal("e5a", fnav),
            signal("e5b", inav),
        )


@dataclass(frozen=True, slots=True)
class EphemerisHealth:
    """Receiver-reported health and, when documented, its ephemeris signal."""

    system: str
    satellite_id: int
    raw: int
    source: str
    signal: str | None = None

    @property
    def healthy(self) -> bool | None:
        return {0: True, 1: False}.get(self.raw)

    @classmethod
    def from_record(cls, record: Record) -> "EphemerisHealth":
        if record.name == "GLOEPH":
            # R1.15 defines Sloto as GLONASS slot + 37.
            if record.integer("sloto") <= 37:
                raise ValueError("GLOEPH slot identifier must be greater than 37")
            return cls(
                "GLONASS",
                record.integer("sloto") - 37,
                record.integer("health"),
                record.name,
            )
        if record.name == "BDSEPH":
            return cls(
                "BeiDou",
                record.integer("prn"),
                record.integer("health"),
                record.name,
            )
        if record.name == "BD3EPH":
            signal = {0: "B1C", 1: "B2a", 2: "B2b"}.get(record.integer("freqtype"))
            return cls(
                "BeiDou",
                record.integer("prn"),
                record.integer("health"),
                record.name,
                signal,
            )
        raise ValueError("expected a GLOEPH, BDSEPH or BD3EPH record")
