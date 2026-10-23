"""Extended log families and their decoders."""

from dataclasses import replace
from enum import StrEnum

from um982py._firmware_layouts import LAYOUTS
from um982py._firmware_navigation import visibility_fields
from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, CommandResponse, Message
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record

_BINARY_IDS = {
    "RTKSTATUS2": 691,
    "RTKSTATUSD": 515,
    "RTKSTATUS2D": 692,
    "PTOBSINFO": 221,
    "BESTGNSSPOS": 1429,
    "BESTGNSSVEL": 99,
    "BESTPOS2": 42,
    "BESTVEL2": 99,
    "BESTSATS": 1194,
    "ALIGNDOP": 1332,
    "BSLNENUHD": 60231,
    "BSLNXYZHD": 60229,
    "ALIGNBSLNENU": 1315,
    "ALIGNBSLNXYZ": 1314,
    "ANT1GROUP": 523,
    "ANT2GROUP": 524,
    "BESTPOS": 42,
    "PSRPOS": 47,
    "RTKPOS": 141,
    "BESTVEL": 99,
    "TIME": 101,
    "RANGE": 43,
    "RANGEH": 6005,
    "HEADINGOFFSET": 8000,
    "PPSSTATUS": 9000,
    "ENVINFO": 11779,
    "ANTENNA": 51,
    "ANTENNASTATUS": 52,
    "DOPPVEL": 92,
    "DOPPVELH": 2074,
    "SPOOFINFO": 530,
    "BESTXYZ": 241,
    "SATVIS": 48,
    "SATVIS2": 1043,
    "REFSTATION": 175,
    "PSRDOP": 174,
    "PSRDOP2": 2059,
    "RTKDOP": 952,
    "RTKDOP2": 2025,
    "RTKVEL": 216,
    "RTKVEL2": 2024,
    "PSRVEL": 100,
    "PSRVEL2": 2058,
}


class FirmwareLog(StrEnum):
    RTKSTATUS2 = "RTKSTATUS2"
    RTKSTATUSD = "RTKSTATUSD"
    RTKSTATUS2D = "RTKSTATUS2D"
    PTOBSINFO = "PTOBSINFO"
    BESTPOS = "BESTPOS"
    PSRPOS = "PSRPOS"
    RTKPOS = "RTKPOS"
    BESTVEL = "BESTVEL"
    TIME = "TIME"
    RANGE = "RANGE"
    RANGEH = "RANGEH"
    HEADINGOFFSET = "HEADINGOFFSET"
    PPSSTATUS = "PPSSTATUS"
    ENVINFO = "ENVINFO"
    RXSTATUS = "RXSTATUS"
    ANTENNA = "ANTENNA"
    ANTENNASTATUS = "ANTENNASTATUS"
    DOPPVEL = "DOPPVEL"
    DOPPVELH = "DOPPVELH"
    SPOOFINFO = "SPOOFINFO"
    BESTXYZ = "BESTXYZ"
    SATVIS = "SATVIS"
    SATVIS2 = "SATVIS2"
    REFSTATION = "REFSTATION"
    PSRDOP = "PSRDOP"
    PSRDOP2 = "PSRDOP2"
    RTKDOP = "RTKDOP"
    RTKDOP2 = "RTKDOP2"
    RTKVEL = "RTKVEL"
    RTKVEL2 = "RTKVEL2"
    PSRVEL = "PSRVEL"
    PSRVEL2 = "PSRVEL2"
    BESTGNSSPOS = "BESTGNSSPOS"
    BESTGNSSVEL = "BESTGNSSVEL"
    BESTPOS2 = "BESTPOS2"
    BESTVEL2 = "BESTVEL2"
    BESTSATS = "BESTSATS"
    ALIGNDOP = "ALIGNDOP"
    BSLNENUHD = "BSLNENUHD"
    BSLNXYZHD = "BSLNXYZHD"
    ALIGNBSLNENU = "ALIGNBSLNENU"
    ALIGNBSLNXYZ = "ALIGNBSLNXYZ"
    ANT1GROUP = "ANT1GROUP"
    ANT2GROUP = "ANT2GROUP"

    def wire_name(self, *, binary: bool = False) -> str:
        if binary and self.value not in _BINARY_IDS:
            raise ValueError(f"{self.value} has no verified binary layout")
        return self.value + ("B" if binary else "A")

    @property
    def onchanged_only(self) -> bool:
        """Return true when only ``ONCHANGED`` output is accepted."""
        return self in _ONCHANGED_ONLY

    def request(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Message]:
        return logging.request(
            self.wire_name(binary=binary),
            port=port,
            message_id=_BINARY_IDS.get(self.value),
        )

    def read(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Record]:
        """Decode one reply frame, or use Receiver.collect() for all SATVIS2 systems."""
        command = self.request(binary=binary, port=port)
        return Command(command.text, command.matches, self.decode)

    def decode(self, message: Message) -> Record:
        binary = isinstance(message, BinaryMessage)
        if binary and self.value not in _BINARY_IDS:
            raise ProtocolError(f"{self.value} has no verified binary layout")
        if not self.request(binary=binary).matches(message):
            raise ProtocolError(f"Expected {self.value}")
        if isinstance(message, BinaryMessage):
            values: bytes | tuple[str, ...] = message.payload
        elif isinstance(message, AsciiMessage):
            values = message.fields
            if self == self.HEADINGOFFSET and len(values) == 3 and values[-1] == "":
                values = values[:-1]
            if self == self.SATVIS2:
                values = visibility_fields(values)
        else:
            raise ProtocolError("Expected an extended data log")
        return replace(BodyReader(values).read(LAYOUTS[self.value]), message=message)

    def output(
        self,
        interval: float | Trigger = 1,
        *,
        binary: bool = False,
        port: Port | None = None,
    ) -> Command[CommandResponse]:
        if self in (self.HEADINGOFFSET, self.RXSTATUS):
            raise ValueError(f"{self.value} only has verified one-shot queries")
        if self.onchanged_only and interval != Trigger.ON_CHANGED:
            raise ValueError(f"{self.value} requires ONCHANGED output")
        return logging.output(self.wire_name(binary=binary), interval, port=port)

    def stop(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[CommandResponse]:
        return logging.stop(self.wire_name(binary=binary), port=port)


_ONCHANGED_ONLY = frozenset(
    {
        FirmwareLog.ALIGNDOP,
        FirmwareLog.BSLNENUHD,
        FirmwareLog.BSLNXYZHD,
        FirmwareLog.ALIGNBSLNENU,
        FirmwareLog.ALIGNBSLNXYZ,
    }
)
