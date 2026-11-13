"""Select documented ANT2 solutions while preserving captured wire messages."""

from collections import Counter
from dataclasses import dataclass

from um982py.commands import Log
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.messages import CommandResponse, Message, Record

_SECONDARY: dict[Log, Log] = {
    Log.RANGE: Log.RANGEH,
    Log.BESTPOS: Log.BESTNAVH,
    Log.BESTXYZ: Log.BESTNAVXYZH,
    Log.BESTVEL: Log.BESTNAVH,
    Log.PSRPOS: Log.SPPNAVH,
    Log.RTKPOS: Log.ADRNAVH,
    Log.PSRDOP: Log.SPPDOPH,
    Log.RTKDOP: Log.ADRDOPH,
    Log.DOPPVEL: Log.DOPPVELH,
    Log.PSRVEL: Log.PSRVEL2,
    Log.RTKVEL: Log.RTKVEL2,
    Log.OBSVM: Log.OBSVH,
    Log.OBSVMCMP: Log.OBSVHCMP,
    Log.BESTNAV: Log.BESTNAVH,
    Log.BESTNAVXYZ: Log.BESTNAVXYZH,
    Log.ADRNAV: Log.ADRNAVH,
    Log.PPPNAV: Log.PPPNAVH,
    Log.SPPNAV: Log.SPPNAVH,
    Log.STADOP: Log.STADOPH,
    Log.ADRDOP: Log.ADRDOPH,
    Log.SPPDOP: Log.SPPDOPH,
    Log.GPGGA: Log.GPGGAH,
    Log.GPGLL: Log.GPGLLH,
    Log.GPGNS: Log.GPGNSH,
    Log.GPGRS: Log.GPGRSH,
    Log.GPGSA: Log.GPGSAH,
    Log.GPGST: Log.GPGSTH,
    Log.GPGSV: Log.GPGSVH,
    Log.GPRMC: Log.GPRMCH,
    Log.GPVTG: Log.GPVTGH,
}


@dataclass(frozen=True, slots=True)
class AntennaLog:
    """Keep analysis keys stable while retaining the true source frame and fields."""

    logical: Log
    wire: Log

    @property
    def value(self) -> str:
        return self.logical.value

    def wire_name(self, *, binary: bool = False) -> str:
        return self.wire.wire_name(binary=binary)

    def request(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Message]:
        return self.wire.request(binary=binary, port=port)

    def output(
        self,
        interval: float | Trigger | None = None,
        *,
        rate_hz: float | None = None,
        binary: bool = False,
        port: Port | None = None,
    ) -> Command[CommandResponse]:
        return self.wire.output(interval, rate_hz=rate_hz, binary=binary, port=port)

    def read(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Record]:
        request = self.request(binary=binary, port=port)
        return Command(request.text, request.matches, self.decode)

    def decode(self, message: Message) -> Record:
        record = self.wire.decode(message)
        if self.logical in (Log.PSRDOP, Log.RTKDOP):
            return Record(
                record.name,
                (
                    *record.entries,
                    ("elev_mask", record["cutoff"]),
                    ("count_sats", record["count_prn"]),
                ),
                record.message,
            )
        return record


def antenna_log(log: Log | AntennaLog, antenna: int | str = 1) -> Log | AntennaLog:
    """Select ANT2 where supported and leave receiver-wide logs unchanged."""
    selected = antenna_index(antenna)
    if isinstance(log, AntennaLog) or selected == 1:
        return log
    if log in (
        Log.PTOBSINFO,
        Log.BESTGNSSPOS,
        Log.BESTGNSSVEL,
        Log.BESTSATS,
        Log.PPPDOP,
        Log.TROPINFO,
    ):
        raise ValueError(f"{log.value} has no verified secondary-antenna equivalent")
    wire = _SECONDARY.get(log)
    return log if wire is None else AntennaLog(log, wire)


_AMBIGUOUS = {
    secondary for secondary, count in Counter(_SECONDARY.values()).items() if count > 1
}
"""Targets shared by several primary logs have ambiguous reverse mappings."""

_MIRROR: dict[Log, Log] = {}
for _primary, _secondary in _SECONDARY.items():
    if _secondary in _AMBIGUOUS:
        continue
    _MIRROR[_primary] = _secondary
    _MIRROR[_secondary] = _primary


def antenna_index(antenna: int | str) -> int:
    """Number of the named antenna input: 1 for primary, 2 for secondary."""
    if type(antenna) is int and antenna in (1, 2):
        return antenna
    if antenna in ("primary", "1"):
        return 1
    if antenna in ("secondary", "2"):
        return 2
    raise ValueError("antenna must be primary/1 or secondary/2")


def other_antenna(antenna: int | str) -> str:
    """Return the other antenna input."""
    return "secondary" if antenna_index(antenna) == 1 else "primary"


def mirror(log: Log) -> Log:
    """Return the wire log of the other antenna input, when one is documented.

    Receiver-wide logs, baselines, and targets shared by several primary logs
    keep their original scope.
    """
    return _MIRROR.get(log, log)


def swap_antenna(log: Log | AntennaLog) -> Log | AntennaLog:
    """Measure the same quantity through the other antenna input.

    An :class:`AntennaLog` keeps its logical key when the wire input changes.
    """
    logical = log.logical if isinstance(log, AntennaLog) else log
    wire = log.wire if isinstance(log, AntennaLog) else log
    return AntennaLog(logical, mirror(wire))
