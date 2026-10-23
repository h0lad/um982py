"""The documented log families and their decoders."""

from enum import StrEnum

from um982py.commands import logging
from um982py.commands.catalog import LOGS, LogDefinition
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import BinaryMessage, CommandResponse, Message
from um982py.messages.decode import decode_log
from um982py.messages.record import Record


class Log(StrEnum):
    VERSION = "VERSION"
    OBSVM = "OBSVM"
    OBSVH = "OBSVH"
    OBSVMCMP = "OBSVMCMP"
    OBSVHCMP = "OBSVHCMP"
    OBSVBASE = "OBSVBASE"
    BASEINFO = "BASEINFO"
    GPSION = "GPSION"
    BD3ION = "BD3ION"
    BDSION = "BDSION"
    GALION = "GALION"
    GPSUTC = "GPSUTC"
    BD3UTC = "BD3UTC"
    BDSUTC = "BDSUTC"
    GALUTC = "GALUTC"
    GPSEPH = "GPSEPH"
    QZSSEPH = "QZSSEPH"
    BD3EPH = "BD3EPH"
    BDSEPH = "BDSEPH"
    GLOEPH = "GLOEPH"
    GALEPH = "GALEPH"
    IRNSSEPH = "IRNSSEPH"
    AGRIC = "AGRIC"
    PVTSLN = "PVTSLN"
    UNILOGLIST = "UNILOGLIST"
    BESTNAV = "BESTNAV"
    BESTNAVXYZ = "BESTNAVXYZ"
    BESTNAVH = "BESTNAVH"
    BESTNAVXYZH = "BESTNAVXYZH"
    BESTSAT = "BESTSAT"
    ADRNAV = "ADRNAV"
    ADRNAVH = "ADRNAVH"
    PPPNAV = "PPPNAV"
    PPPNAVH = "PPPNAVH"
    SPPNAV = "SPPNAV"
    SPPNAVH = "SPPNAVH"
    STADOP = "STADOP"
    STADOPH = "STADOPH"
    ADRDOP = "ADRDOP"
    ADRDOPH = "ADRDOPH"
    PPPDOP = "PPPDOP"
    PPPDOP2 = "PPPDOP2"
    SPPDOP = "SPPDOP"
    SPPDOPH = "SPPDOPH"
    SATSINFO = "SATSINFO"
    BASEPOS = "BASEPOS"
    SATELLITE = "SATELLITE"
    SATECEF = "SATECEF"
    RECTIME = "RECTIME"
    UNIHEADING = "UNIHEADING"
    UNIHEADING2 = "UNIHEADING2"
    HEADINGSTATUS = "HEADINGSTATUS"
    RTKSTATUS = "RTKSTATUS"
    AGNSSSTATUS = "AGNSSSTATUS"
    RTCSTATUS = "RTCSTATUS"
    JAMSTATUS = "JAMSTATUS"
    FREQJAMSTATUS = "FREQJAMSTATUS"
    RTCMSTATUS = "RTCMSTATUS"
    HWSTATUS = "HWSTATUS"
    AGC = "AGC"
    KSXT = "KSXT"
    INFOPART1 = "INFOPART1"
    INFOPART2 = "INFOPART2"
    MSPOS = "MSPOS"
    TROPINFO = "TROPINFO"
    PPPB2BINFO1 = "PPPB2BINFO1"
    PPPB2BINFO2 = "PPPB2BINFO2"
    PPPB2BINFO3 = "PPPB2BINFO3"
    PPPB2BINFO4 = "PPPB2BINFO4"
    PPPB2BINFO5 = "PPPB2BINFO5"
    PPPB2BINFO6 = "PPPB2BINFO6"
    PPPB2BINFO7 = "PPPB2BINFO7"
    APPPNAV = "APPPNAV"
    RPPPNAV = "RPPPNAV"
    RPPPDOP = "RPPPDOP"
    LBANDAUTH = "LBANDAUTH"
    LBANDBEAM = "LBANDBEAM"
    LBANDTRACKSTATUS = "LBANDTRACKSTATUS"
    LBANDUSERDATA = "LBANDUSERDATA"
    E6MASKBLOCK = "E6MASKBLOCK"
    E6ORBITBLOCK = "E6ORBITBLOCK"
    E6CLOCKFULLBLOCK = "E6CLOCKFULLBLOCK"
    E6CLOCKSUBBLOCK = "E6CLOCKSUBBLOCK"
    E6CBIASBLOCK = "E6CBIASBLOCK"
    E6PBIASBLOCK = "E6PBIASBLOCK"
    L1SMT47 = "L1SMT47"
    L1SMT48 = "L1SMT48"
    L1SMT49 = "L1SMT49"
    L1SMT50 = "L1SMT50"
    L6MDCTYPE1 = "L6MDCTYPE1"
    L6MDCTYPE2 = "L6MDCTYPE2"
    L6MDCTYPE3 = "L6MDCTYPE3"
    L6MDCTYPE4 = "L6MDCTYPE4"
    L6MDCTYPE5 = "L6MDCTYPE5"
    L6MDCTYPE7 = "L6MDCTYPE7"
    BSLNENUHD2 = "BSLNENUHD2"
    BSLNXYZHD2 = "BSLNXYZHD2"
    DOPHD2 = "DOPHD2"
    RTKSTATUS2 = "RTKSTATUS2"
    GPDTM = "GPDTM"
    GPGBS = "GPGBS"
    GPGGA = "GPGGA"
    GPGLL = "GPGLL"
    GPGNS = "GPGNS"
    GPGRS = "GPGRS"
    GPGSA = "GPGSA"
    GPGST = "GPGST"
    GPGSV = "GPGSV"
    GPTHS = "GPTHS"
    GPRMC = "GPRMC"
    GPROT = "GPROT"
    GPVTG = "GPVTG"
    GPZDA = "GPZDA"
    GPGGAH = "GPGGAH"
    GPGLLH = "GPGLLH"
    GPGNSH = "GPGNSH"
    GPGRSH = "GPGRSH"
    GPGSAH = "GPGSAH"
    GPGSTH = "GPGSTH"
    GPGSVH = "GPGSVH"
    GPRMCH = "GPRMCH"
    GPVTGH = "GPVTGH"
    GPTHS2 = "GPTHS2"
    GPHPR = "GPHPR"
    GPHPR2 = "GPHPR2"
    GPTRA2 = "GPTRA2"
    GPROT2 = "GPROT2"
    GPHPD = "GPHPD"
    QZQSM = "QZQSM"
    EVENTFLAG = "EVENTFLAG"
    EVENTSLN = "EVENTSLN"

    RTCM63 = "RTCM63"
    RTCM1001 = "RTCM1001"
    RTCM1002 = "RTCM1002"
    RTCM1003 = "RTCM1003"
    RTCM1004 = "RTCM1004"
    RTCM1005 = "RTCM1005"
    RTCM1006 = "RTCM1006"
    RTCM1007 = "RTCM1007"
    RTCM1009 = "RTCM1009"
    RTCM1010 = "RTCM1010"
    RTCM1011 = "RTCM1011"
    RTCM1012 = "RTCM1012"
    RTCM1019 = "RTCM1019"
    RTCM1020 = "RTCM1020"
    RTCM1033 = "RTCM1033"
    RTCM1042 = "RTCM1042"
    RTCM1045 = "RTCM1045"
    RTCM1046 = "RTCM1046"
    RTCM1074 = "RTCM1074"
    RTCM1075 = "RTCM1075"
    RTCM1084 = "RTCM1084"
    RTCM1085 = "RTCM1085"
    RTCM1104 = "RTCM1104"
    RTCM1105 = "RTCM1105"
    RTCM1123 = "RTCM1123"
    RTCM1124 = "RTCM1124"
    RTCM1125 = "RTCM1125"
    RTCM1126 = "RTCM1126"
    RTCM1127 = "RTCM1127"

    @property
    def definition(self) -> LogDefinition:
        return LOGS[self.value]

    def wire_name(self, *, binary: bool = False) -> str:
        definition = self.definition
        if not binary:
            return definition.ascii_command
        if definition.binary_command is None:
            raise ValueError(f"{self.value} has no documented binary output")
        return definition.binary_command

    def request(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Message]:
        if self.definition.changed_only:
            raise ValueError(f"{self.value} requires ONCHANGED output")
        return logging.request(
            self.wire_name(binary=binary),
            port=port,
            message_id=self.definition.message_id,
        )

    def output(
        self,
        interval: float | Trigger = 1,
        *,
        binary: bool = False,
        port: Port | None = None,
    ) -> Command[CommandResponse]:
        if self.definition.changed_only and interval != Trigger.ON_CHANGED:
            raise ValueError(f"{self.value} requires ONCHANGED output")
        return logging.output(self.wire_name(binary=binary), interval, port=port)

    def read(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[Record]:
        command = self.request(binary=binary, port=port)
        return Command(command.text, command.matches, self.decode)

    def decode(self, message: Message) -> Record:
        if (
            isinstance(message, BinaryMessage)
            and self.definition.binary_command is None
        ):
            raise ProtocolError(f"{self.value} has no binary body")
        command = logging.request(
            self.wire_name(binary=isinstance(message, BinaryMessage)),
            message_id=self.definition.message_id,
        )
        if not command.matches(message):
            raise ProtocolError(f"Expected {self.value}")
        return decode_log(message)

    def stop(
        self, *, binary: bool = False, port: Port | None = None
    ) -> Command[CommandResponse]:
        return logging.stop(self.wire_name(binary=binary), port=port)
