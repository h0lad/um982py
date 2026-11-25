"""Convenient views of the receiver's SATSINFO satellite report."""

from dataclasses import dataclass

from um982py.messages.enums import SatelliteSystem
from um982py.messages.record import Record
from um982py.signals import _SIGNALS as _RANGE_SIGNALS


def _satsinfo_signals() -> dict[int, dict[int, str]]:
    """Name SATSINFO signals from N4 R1.4 table 7-112.

    The table reuses the RANGE identifiers of table 7-55 except for the GLONASS
    names, the SBAS L5 entry and the QZSS identifiers below.
    """
    table: dict[int, dict[int, str]] = {}
    for (system, signal), (name, _, _) in _RANGE_SIGNALS.items():
        table.setdefault(system, {})[signal] = name
    table[1] |= {0: "L1 C/A", 5: "L2 C/A"}
    table[2][6] = "L5 I"
    table[5] = {
        0: "L1 C/A",
        6: "L5 data",
        14: "L5 pilot",
        17: "L2C L",
        18: "L61 data",
        22: "L61 pilot",
        24: "L62 data 1",
        25: "L62 data 2",
    }
    return table


_SIGNALS = _satsinfo_signals()


def _constellation(system_id: int) -> str | None:
    try:
        return SatelliteSystem(system_id).name
    except ValueError:
        return None


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
        return _constellation(self.system_id)

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
        return _constellation(next(iter(systems)))


def satellites_from_record(record: Record) -> tuple[Satellite, ...]:
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
