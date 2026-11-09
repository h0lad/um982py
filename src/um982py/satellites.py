"""Convenient views of the receiver's SATSINFO satellite report."""

from dataclasses import dataclass

from um982py.messages.record import Record

_SYSTEMS = ("GPS", "GLONASS", "SBAS", "Galileo", "BeiDou", "QZSS", "NavIC")

# SATSINFO uses the frequency identifiers from N4 R1.4 table 7-112.
# Its QZSS identifiers differ from the RANGE tracking-status identifiers.
_SIGNALS: dict[int, dict[int, str]] = {
    0: {
        0: "L1 C/A",
        3: "L1C pilot",
        6: "L5 data",
        9: "L2 P(Y)",
        11: "L1C data",
        14: "L5 pilot",
        17: "L2C L",
    },
    1: {0: "L1 C/A", 5: "L2 C/A", 6: "G3 I", 7: "G3 Q"},
    2: {0: "L1 C/A", 6: "L5 I"},
    3: {1: "E1 B", 2: "E1 C", 12: "E5a pilot", 17: "E5b pilot", 18: "E6 B", 22: "E6 C"},
    4: {
        0: "B1 I",
        4: "B1 Q",
        5: "B2 Q",
        6: "B3 Q",
        8: "B1C pilot",
        12: "B2a pilot",
        13: "B2b I",
        17: "B2 I",
        21: "B3 I",
        23: "B1C data",
        28: "B2a data",
    },
    5: {
        0: "L1 C/A",
        6: "L5 data",
        14: "L5 pilot",
        17: "L2C L",
        18: "L61 data",
        22: "L61 pilot",
        24: "L62 data 1",
        25: "L62 data 2",
    },
    6: {6: "L5 data", 14: "L5 pilot"},
}


@dataclass(frozen=True, slots=True)
class SatelliteSignal:
    """A tracked SATSINFO signal and its receiver-reported signal strength.

    Unknown identifiers retain their numeric values and have no decoded name.
    """

    system_id: int
    signal_id: int
    snr: int

    @property
    def constellation(self) -> str | None:
        """Return the constellation name when the system identifier is known."""
        if 0 <= self.system_id < len(_SYSTEMS):
            return _SYSTEMS[self.system_id]
        return None

    @property
    def name(self) -> str | None:
        """Return the signal name when its SATSINFO identifier is known."""
        return _SIGNALS.get(self.system_id, {}).get(self.signal_id)


@dataclass(frozen=True, slots=True)
class Satellite:
    """One tracked satellite with its reported sky position and signals."""

    prn: int
    azimuth_deg: int
    elevation_deg: int
    signals: tuple[SatelliteSignal, ...]

    @property
    def constellation(self) -> str | None:
        """Return its constellation when every reported signal agrees."""
        systems = {signal.system_id for signal in self.signals}
        if len(systems) != 1:
            return None
        system = next(iter(systems))
        if 0 <= system < len(_SYSTEMS):
            return _SYSTEMS[system]
        return None


def satellites_from_record(record: Record) -> tuple[Satellite, ...]:
    """Convert a decoded SATSINFO record into satellites and named signals."""
    if record.name != "SATSINFO":
        raise ValueError("expected a SATSINFO record")
    return tuple(
        Satellite(
            prn=satellite.integer("prn"),
            azimuth_deg=satellite.integer("azimuth"),
            elevation_deg=satellite.integer("elevation"),
            signals=tuple(
                SatelliteSignal(
                    system_id=signal.integer("system"),
                    signal_id=signal.integer("signal"),
                    snr=signal.integer("snr"),
                )
                for signal in satellite.records("frequencies")
            ),
        )
        for satellite in record.records("satellites")
    )
