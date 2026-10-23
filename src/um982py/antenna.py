"""Select documented ANT2 solutions without rewriting captured wire messages."""

from collections import Counter
from dataclasses import dataclass

from um982py._firmware_logs import FirmwareLog
from um982py.commands import Log
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.messages import CommandResponse, Message, Record

_SECONDARY: dict[Log | FirmwareLog, Log | FirmwareLog] = {
    FirmwareLog.RANGE: FirmwareLog.RANGEH,
    FirmwareLog.BESTPOS: Log.BESTNAVH,
    FirmwareLog.BESTXYZ: Log.BESTNAVXYZH,
    FirmwareLog.BESTVEL: Log.BESTNAVH,
    FirmwareLog.PSRPOS: Log.SPPNAVH,
    FirmwareLog.RTKPOS: Log.ADRNAVH,
    FirmwareLog.PSRDOP: Log.SPPDOPH,
    FirmwareLog.RTKDOP: Log.ADRDOPH,
    FirmwareLog.DOPPVEL: FirmwareLog.DOPPVELH,
    FirmwareLog.PSRVEL: FirmwareLog.PSRVEL2,
    FirmwareLog.RTKVEL: FirmwareLog.RTKVEL2,
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

    logical: Log | FirmwareLog
    wire: Log | FirmwareLog

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
        interval: float | Trigger = 1,
        *,
        binary: bool = False,
        port: Port | None = None,
    ) -> Command[CommandResponse]:
        return self.wire.output(interval, binary=binary, port=port)

    def read(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Record]:
        request = self.request(binary=binary, port=port)
        return Command(request.text, request.matches, self.decode)

    def decode(self, message: Message) -> Record:
        record = self.wire.decode(message)
        if self.logical in (FirmwareLog.PSRDOP, FirmwareLog.RTKDOP):
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


def antenna_log(
    log: Log | FirmwareLog | AntennaLog, antenna: str = "primary"
) -> Log | FirmwareLog | AntennaLog:
    """Select ANT2 where supported and leave receiver-wide logs unchanged."""
    if isinstance(log, AntennaLog) or antenna in ("primary", "1"):
        return log
    if antenna not in ("secondary", "2"):
        raise ValueError("antenna must be primary/1 or secondary/2")
    if log in (
        FirmwareLog.PTOBSINFO,
        FirmwareLog.BESTGNSSPOS,
        FirmwareLog.BESTGNSSVEL,
        FirmwareLog.BESTSATS,
        Log.PPPDOP,
        Log.TROPINFO,
    ):
        raise ValueError(f"{log.value} has no verified secondary-antenna equivalent")
    wire = _SECONDARY.get(log)
    return log if wire is None else AntennaLog(log, wire)


_AMBIGUOUS = {
    secondary for secondary, count in Counter(_SECONDARY.values()).items() if count > 1
}
"""Targets that several primary logs share, so they cannot be mirrored back."""

_MIRROR: dict[Log | FirmwareLog, Log | FirmwareLog] = {}
for _primary, _secondary in _SECONDARY.items():
    if _secondary in _AMBIGUOUS:
        continue
    _MIRROR[_primary] = _secondary
    _MIRROR[_secondary] = _primary


def antenna_index(antenna: str) -> int:
    """Number of the named antenna input: 1 for primary, 2 for secondary."""
    if antenna in ("primary", "1"):
        return 1
    if antenna in ("secondary", "2"):
        return 2
    raise ValueError("antenna must be primary/1 or secondary/2")


def other_antenna(antenna: str) -> str:
    """Name the antenna input that is not the one named."""
    return "secondary" if antenna_index(antenna) == 1 else "primary"


def mirror(log: Log | FirmwareLog) -> Log | FirmwareLog:
    """Return the wire log of the other antenna input, when one is documented.

    Receiver-wide logs and baselines keep their scope, and a target shared by
    several primary logs is left unchanged instead of being assigned to an
    arbitrary partner.
    """
    return _MIRROR.get(log, log)


def swap_antenna(log: Log | FirmwareLog | AntennaLog) -> Log | FirmwareLog | AntennaLog:
    """Measure the same quantity through the other antenna input.

    The logical key of an :class:`AntennaLog` is retained, so an example that
    asks for ``RANGE`` keeps that key while the wire command switches inputs.
    """
    logical = log.logical if isinstance(log, AntennaLog) else log
    wire = log.wire if isinstance(log, AntennaLog) else log
    return AntennaLog(logical, mirror(wire))
