"""Log catalogue types and lookup tables."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class LogDefinition:
    name: str
    message_id: int | None
    section: str
    ascii_command: str
    binary_command: str | None
    changed_only: bool


LOGS: Mapping[str, LogDefinition] = MappingProxyType(
    {
        "VERSION": LogDefinition("VERSION", 37, "7.3.1", "VERSIONA", "VERSIONB", False),
        "OBSVM": LogDefinition("OBSVM", 12, "7.3.2", "OBSVMA", "OBSVMB", False),
        "OBSVH": LogDefinition("OBSVH", 13, "7.3.3", "OBSVHA", "OBSVHB", False),
        "OBSVMCMP": LogDefinition(
            "OBSVMCMP", 138, "7.3.4", "OBSVMCMPA", "OBSVMCMPB", False
        ),
        "OBSVHCMP": LogDefinition(
            "OBSVHCMP", 139, "7.3.5", "OBSVHCMPA", "OBSVHCMPB", False
        ),
        "OBSVBASE": LogDefinition(
            "OBSVBASE", 284, "7.3.6", "OBSVBASEA", "OBSVBASEB", True
        ),
        "BASEINFO": LogDefinition(
            "BASEINFO", 176, "7.3.7", "BASEINFOA", "BASEINFOB", False
        ),
        "GPSION": LogDefinition("GPSION", 8, "7.3.8", "GPSIONA", "GPSIONB", False),
        "BD3ION": LogDefinition("BD3ION", 21, "7.3.9", "BD3IONA", "BD3IONB", False),
        "BDSION": LogDefinition("BDSION", 4, "7.3.10", "BDSIONA", "BDSIONB", False),
        "GALION": LogDefinition("GALION", 9, "7.3.11", "GALIONA", "GALIONB", False),
        "GPSUTC": LogDefinition("GPSUTC", 19, "7.3.12", "GPSUTCA", "GPSUTCB", False),
        "BD3UTC": LogDefinition("BD3UTC", 22, "7.3.13", "BD3UTCA", "BD3UTCB", False),
        "BDSUTC": LogDefinition("BDSUTC", 2012, "7.3.14", "BDSUTCA", "BDSUTCB", False),
        "GALUTC": LogDefinition("GALUTC", 20, "7.3.15", "GALUTCA", "GALUTCB", False),
        "GPSEPH": LogDefinition("GPSEPH", 106, "7.3.16", "GPSEPHA", "GPSEPHB", False),
        "QZSSEPH": LogDefinition(
            "QZSSEPH", 110, "7.3.17", "QZSSEPHA", "QZSSEPHB", False
        ),
        "BD3EPH": LogDefinition("BD3EPH", 2999, "7.3.18", "BD3EPHA", "BD3EPHB", False),
        "BDSEPH": LogDefinition("BDSEPH", 108, "7.3.19", "BDSEPHA", "BDSEPHB", False),
        "GLOEPH": LogDefinition("GLOEPH", 107, "7.3.20", "GLOEPHA", "GLOEPHB", False),
        "GALEPH": LogDefinition("GALEPH", 109, "7.3.21", "GALEPHA", "GALEPHB", False),
        "IRNSSEPH": LogDefinition(
            "IRNSSEPH", 112, "7.3.22", "IRNSSEPHA", "IRNSSEPHB", False
        ),
        "AGRIC": LogDefinition("AGRIC", 11276, "7.3.23", "AGRICA", "AGRICB", False),
        "PVTSLN": LogDefinition("PVTSLN", 1021, "7.3.24", "PVTSLNA", "PVTSLNB", False),
        "UNILOGLIST": LogDefinition(
            "UNILOGLIST", None, "7.3.25", "UNILOGLIST", None, False
        ),
        "BESTNAV": LogDefinition(
            "BESTNAV", 2118, "7.3.26", "BESTNAVA", "BESTNAVB", False
        ),
        "BESTNAVXYZ": LogDefinition(
            "BESTNAVXYZ", 240, "7.3.27", "BESTNAVXYZA", "BESTNAVXYZB", False
        ),
        "BESTNAVH": LogDefinition(
            "BESTNAVH", 2119, "7.3.28", "BESTNAVHA", "BESTNAVHB", False
        ),
        "BESTNAVXYZH": LogDefinition(
            "BESTNAVXYZH", 242, "7.3.29", "BESTNAVXYZHA", "BESTNAVXYZHB", False
        ),
        "BESTSAT": LogDefinition(
            "BESTSAT", 1041, "7.3.30", "BESTSATA", "BESTSATB", False
        ),
        "ADRNAV": LogDefinition("ADRNAV", 142, "7.3.31", "ADRNAVA", "ADRNAVB", False),
        "ADRNAVH": LogDefinition(
            "ADRNAVH", 2117, "7.3.32", "ADRNAVHA", "ADRNAVHB", False
        ),
        "PPPNAV": LogDefinition("PPPNAV", 1026, "7.3.33", "PPPNAVA", "PPPNAVB", False),
        "PPPNAVH": LogDefinition(
            "PPPNAVH", 5996, "7.5.79", "PPPNAVHA", "PPPNAVHB", False
        ),
        "SPPNAV": LogDefinition("SPPNAV", 46, "7.3.34", "SPPNAVA", "SPPNAVB", False),
        "SPPNAVH": LogDefinition(
            "SPPNAVH", 2116, "7.3.35", "SPPNAVHA", "SPPNAVHB", False
        ),
        "STADOP": LogDefinition("STADOP", 954, "7.3.36", "STADOPA", "STADOPB", False),
        "STADOPH": LogDefinition(
            "STADOPH", 2122, "7.3.37", "STADOPHA", "STADOPHB", False
        ),
        "ADRDOP": LogDefinition("ADRDOP", 953, "7.3.38", "ADRDOPA", "ADRDOPB", False),
        "ADRDOPH": LogDefinition(
            "ADRDOPH", 2121, "7.3.39", "ADRDOPHA", "ADRDOPHB", False
        ),
        "PPPDOP": LogDefinition("PPPDOP", 1025, "7.3.40", "PPPDOPA", "PPPDOPB", False),
        "PPPDOP2": LogDefinition(
            "PPPDOP2", 5995, "7.5.76", "PPPDOP2A", "PPPDOP2B", False
        ),
        "SPPDOP": LogDefinition("SPPDOP", 173, "7.3.41", "SPPDOPA", "SPPDOPB", False),
        "SPPDOPH": LogDefinition(
            "SPPDOPH", 2120, "7.3.42", "SPPDOPHA", "SPPDOPHB", False
        ),
        "SATSINFO": LogDefinition(
            "SATSINFO", 2124, "7.3.43", "SATSINFOA", "SATSINFOB", False
        ),
        "BASEPOS": LogDefinition(
            "BASEPOS", 49, "7.3.44", "BASEPOSA", "BASEPOSB", False
        ),
        "SATELLITE": LogDefinition(
            "SATELLITE", 1042, "7.3.45", "SATELLITEA", "SATELLITEB", False
        ),
        "SATECEF": LogDefinition(
            "SATECEF", 2115, "7.3.46", "SATECEFA", "SATECEFB", False
        ),
        "RECTIME": LogDefinition(
            "RECTIME", 102, "7.3.47", "RECTIMEA", "RECTIMEB", False
        ),
        "UNIHEADING": LogDefinition(
            "UNIHEADING", 972, "7.3.48", "UNIHEADINGA", "UNIHEADINGB", False
        ),
        "UNIHEADING2": LogDefinition(
            "UNIHEADING2", 1331, "7.3.49", "UNIHEADING2A", "UNIHEADING2B", True
        ),
        "HEADINGSTATUS": LogDefinition(
            "HEADINGSTATUS", 521, "7.3.50", "HEADINGSTATUSA", "HEADINGSTATUSB", False
        ),
        "RTKSTATUS": LogDefinition(
            "RTKSTATUS", 509, "7.3.51", "RTKSTATUSA", "RTKSTATUSB", False
        ),
        "AGNSSSTATUS": LogDefinition(
            "AGNSSSTATUS", 512, "7.3.52", "AGNSSSTATUSA", "AGNSSSTATUSB", False
        ),
        "RTCSTATUS": LogDefinition(
            "RTCSTATUS", 510, "7.3.53", "RTCSTATUSA", "RTCSTATUSB", False
        ),
        "JAMSTATUS": LogDefinition(
            "JAMSTATUS", 511, "7.3.54", "JAMSTATUSA", "JAMSTATUSB", False
        ),
        "FREQJAMSTATUS": LogDefinition(
            "FREQJAMSTATUS", 519, "7.3.55", "FREQJAMSTATUSA", "FREQJAMSTATUSB", False
        ),
        "RTCMSTATUS": LogDefinition(
            "RTCMSTATUS", 2125, "7.3.56", "RTCMSTATUSA", "RTCMSTATUSB", True
        ),
        "HWSTATUS": LogDefinition(
            "HWSTATUS", 218, "7.3.57", "HWSTATUSA", "HWSTATUSB", False
        ),
        "AGC": LogDefinition("AGC", 220, "7.3.58", "AGCA", "AGCB", False),
        "KSXT": LogDefinition("KSXT", None, "7.3.59", "KSXT", None, False),
        "INFOPART1": LogDefinition(
            "INFOPART1", 1019, "7.3.60", "INFOPART1A", "INFOPART1B", False
        ),
        "INFOPART2": LogDefinition(
            "INFOPART2", 1020, "7.3.61", "INFOPART2A", "INFOPART2B", False
        ),
        "MSPOS": LogDefinition("MSPOS", 520, "7.3.62", "MSPOSA", "MSPOSB", False),
        "TROPINFO": LogDefinition(
            "TROPINFO", 2318, "7.3.63", "TROPINFOA", "TROPINFOB", True
        ),
        "PPPB2BINFO1": LogDefinition(
            "PPPB2BINFO1", 2302, "7.3.64", "PPPB2BINFO1A", "PPPB2BINFO1B", True
        ),
        "PPPB2BINFO2": LogDefinition(
            "PPPB2BINFO2", 2304, "7.3.65", "PPPB2BINFO2A", "PPPB2BINFO2B", True
        ),
        "PPPB2BINFO3": LogDefinition(
            "PPPB2BINFO3", 2306, "7.3.66", "PPPB2BINFO3A", "PPPB2BINFO3B", True
        ),
        "PPPB2BINFO4": LogDefinition(
            "PPPB2BINFO4", 2308, "7.3.67", "PPPB2BINFO4A", "PPPB2BINFO4B", True
        ),
        "PPPB2BINFO5": LogDefinition(
            "PPPB2BINFO5", 2310, "7.3.68", "PPPB2BINFO5A", "PPPB2BINFO5B", True
        ),
        "PPPB2BINFO6": LogDefinition(
            "PPPB2BINFO6", 2312, "7.3.69", "PPPB2BINFO6A", "PPPB2BINFO6B", True
        ),
        "PPPB2BINFO7": LogDefinition(
            "PPPB2BINFO7", 2314, "7.3.70", "PPPB2BINFO7A", "PPPB2BINFO7B", True
        ),
        "E6MASKBLOCK": LogDefinition(
            "E6MASKBLOCK", 2319, "7.3.71", "E6MASKBLOCKA", "E6MASKBLOCKB", True
        ),
        "E6ORBITBLOCK": LogDefinition(
            "E6ORBITBLOCK", 2320, "7.3.72", "E6ORBITBLOCKA", "E6ORBITBLOCKB", True
        ),
        "E6CLOCKFULLBLOCK": LogDefinition(
            "E6CLOCKFULLBLOCK",
            2321,
            "7.3.73",
            "E6CLOCKFULLBLOCKA",
            "E6CLOCKFULLBLOCKB",
            True,
        ),
        "E6CLOCKSUBBLOCK": LogDefinition(
            "E6CLOCKSUBBLOCK",
            2322,
            "7.3.74",
            "E6CLOCKSUBBLOCKA",
            "E6CLOCKSUBBLOCKB",
            True,
        ),
        "E6CBIASBLOCK": LogDefinition(
            "E6CBIASBLOCK", 2323, "7.3.75", "E6CBIASBLOCKA", "E6CBIASBLOCKB", True
        ),
        "E6PBIASBLOCK": LogDefinition(
            "E6PBIASBLOCK", 2324, "7.3.76", "E6PBIASBLOCKA", "E6PBIASBLOCKB", True
        ),
        "BSLNENUHD2": LogDefinition(
            "BSLNENUHD2", 1316, "7.3.77", "BSLNENUHD2A", "BSLNENUHD2B", True
        ),
        "BSLNXYZHD2": LogDefinition(
            "BSLNXYZHD2", 1317, "7.3.78", "BSLNXYZHD2A", "BSLNXYZHD2B", True
        ),
        "DOPHD2": LogDefinition("DOPHD2", 1333, "7.3.79", "DOPHD2A", "DOPHD2B", True),
        "GPDTM": LogDefinition("GPDTM", None, "7.1.1.1", "GPDTM", None, False),
        "GPGBS": LogDefinition("GPGBS", None, "7.1.1.2", "GPGBS", None, False),
        "GPGGA": LogDefinition("GPGGA", None, "7.1.1.3", "GPGGA", None, False),
        "GPGLL": LogDefinition("GPGLL", None, "7.1.1.4", "GPGLL", None, False),
        "GPGNS": LogDefinition("GPGNS", None, "7.1.1.5", "GPGNS", None, False),
        "GPGRS": LogDefinition("GPGRS", None, "7.1.1.6", "GPGRS", None, False),
        "GPGSA": LogDefinition("GPGSA", None, "7.1.1.7", "GPGSA", None, False),
        "GPGST": LogDefinition("GPGST", None, "7.1.1.8", "GPGST", None, False),
        "GPGSV": LogDefinition("GPGSV", None, "7.1.1.9", "GPGSV", None, False),
        "GPTHS": LogDefinition("GPTHS", None, "7.1.1.10", "GPTHS", None, False),
        "GPRMC": LogDefinition("GPRMC", None, "7.1.1.11", "GPRMC", None, False),
        "GPROT": LogDefinition("GPROT", None, "7.1.1.12", "GPROT", None, False),
        "GPVTG": LogDefinition("GPVTG", None, "7.1.1.13", "GPVTG", None, False),
        "GPZDA": LogDefinition("GPZDA", None, "7.1.1.14", "GPZDA", None, False),
        "GPGGAH": LogDefinition("GPGGAH", None, "7.2.1", "GPGGAH", None, False),
        "GPGLLH": LogDefinition("GPGLLH", None, "7.2.2", "GPGLLH", None, False),
        "GPGNSH": LogDefinition("GPGNSH", None, "7.2.3", "GPGNSH", None, False),
        "GPGRSH": LogDefinition("GPGRSH", None, "7.2.4", "GPGRSH", None, False),
        "GPGSAH": LogDefinition("GPGSAH", None, "7.2.5", "GPGSAH", None, False),
        "GPGSTH": LogDefinition("GPGSTH", None, "7.2.6", "GPGSTH", None, False),
        "GPGSVH": LogDefinition("GPGSVH", None, "7.2.7", "GPGSVH", None, False),
        "GPRMCH": LogDefinition("GPRMCH", None, "7.2.8", "GPRMCH", None, False),
        "GPVTGH": LogDefinition("GPVTGH", None, "7.2.9", "GPVTGH", None, False),
        "GPTHS2": LogDefinition("GPTHS2", None, "7.2.10", "GPTHS2", None, True),
        "GPHPR": LogDefinition("GPHPR", None, "7.2.11", "GPHPR", None, False),
        "GPHPR2": LogDefinition("GPHPR2", None, "7.2.12", "GPHPR2", None, True),
        "GPTRA2": LogDefinition("GPTRA2", None, "7.2.13", "GPTRA2", None, True),
        "GPROT2": LogDefinition("GPROT2", None, "7.2.14", "GPROT2", None, True),
        "GPHPD": LogDefinition("GPHPD", None, "7.2.15", "GPHPD", None, False),
        "QZQSM": LogDefinition("QZQSM", None, "7.4.16", "QZQSM", None, False),
        "EVENTFLAG": LogDefinition(
            "EVENTFLAG", 312, "Appendix 3", "EVENTFLAGA", "EVENTFLAGB", True
        ),
        "EVENTSLN": LogDefinition(
            "EVENTSLN", 311, "Appendix 3", "EVENTSLNA", "EVENTSLNB", True
        ),
    }
)

RTCM_LOGS: Mapping[str, LogDefinition] = MappingProxyType(
    {
        "RTCM63": LogDefinition("RTCM63", 63, "Appendix 2", "RTCM63", "RTCM63", False),
        "RTCM1001": LogDefinition(
            "RTCM1001", 1001, "Appendix 2", "RTCM1001", "RTCM1001", False
        ),
        "RTCM1002": LogDefinition(
            "RTCM1002", 1002, "Appendix 2", "RTCM1002", "RTCM1002", False
        ),
        "RTCM1003": LogDefinition(
            "RTCM1003", 1003, "Appendix 2", "RTCM1003", "RTCM1003", False
        ),
        "RTCM1004": LogDefinition(
            "RTCM1004", 1004, "Appendix 2", "RTCM1004", "RTCM1004", False
        ),
        "RTCM1005": LogDefinition(
            "RTCM1005", 1005, "Appendix 2", "RTCM1005", "RTCM1005", False
        ),
        "RTCM1006": LogDefinition(
            "RTCM1006", 1006, "Appendix 2", "RTCM1006", "RTCM1006", False
        ),
        "RTCM1007": LogDefinition(
            "RTCM1007", 1007, "Appendix 2", "RTCM1007", "RTCM1007", False
        ),
        "RTCM1009": LogDefinition(
            "RTCM1009", 1009, "Appendix 2", "RTCM1009", "RTCM1009", False
        ),
        "RTCM1010": LogDefinition(
            "RTCM1010", 1010, "Appendix 2", "RTCM1010", "RTCM1010", False
        ),
        "RTCM1011": LogDefinition(
            "RTCM1011", 1011, "Appendix 2", "RTCM1011", "RTCM1011", False
        ),
        "RTCM1012": LogDefinition(
            "RTCM1012", 1012, "Appendix 2", "RTCM1012", "RTCM1012", False
        ),
        "RTCM1019": LogDefinition(
            "RTCM1019", 1019, "Appendix 2", "RTCM1019", "RTCM1019", False
        ),
        "RTCM1020": LogDefinition(
            "RTCM1020", 1020, "Appendix 2", "RTCM1020", "RTCM1020", False
        ),
        "RTCM1033": LogDefinition(
            "RTCM1033", 1033, "Appendix 2", "RTCM1033", "RTCM1033", False
        ),
        "RTCM1042": LogDefinition(
            "RTCM1042", 1042, "Appendix 2", "RTCM1042", "RTCM1042", False
        ),
        "RTCM1045": LogDefinition(
            "RTCM1045", 1045, "Appendix 2", "RTCM1045", "RTCM1045", False
        ),
        "RTCM1046": LogDefinition(
            "RTCM1046", 1046, "Appendix 2", "RTCM1046", "RTCM1046", False
        ),
        "RTCM1074": LogDefinition(
            "RTCM1074", 1074, "Appendix 2", "RTCM1074", "RTCM1074", False
        ),
        "RTCM1075": LogDefinition(
            "RTCM1075", 1075, "Appendix 2", "RTCM1075", "RTCM1075", False
        ),
        "RTCM1084": LogDefinition(
            "RTCM1084", 1084, "Appendix 2", "RTCM1084", "RTCM1084", False
        ),
        "RTCM1085": LogDefinition(
            "RTCM1085", 1085, "Appendix 2", "RTCM1085", "RTCM1085", False
        ),
        "RTCM1104": LogDefinition(
            "RTCM1104", 1104, "Appendix 2", "RTCM1104", "RTCM1104", False
        ),
        "RTCM1105": LogDefinition(
            "RTCM1105", 1105, "Appendix 2", "RTCM1105", "RTCM1105", False
        ),
        "RTCM1123": LogDefinition(
            "RTCM1123", 1123, "Appendix 2", "RTCM1123", "RTCM1123", False
        ),
        "RTCM1124": LogDefinition(
            "RTCM1124", 1124, "Appendix 2", "RTCM1124", "RTCM1124", False
        ),
        "RTCM1125": LogDefinition(
            "RTCM1125", 1125, "Appendix 2", "RTCM1125", "RTCM1125", False
        ),
        "RTCM1126": LogDefinition(
            "RTCM1126", 1126, "Appendix 2", "RTCM1126", "RTCM1126", False
        ),
        "RTCM1127": LogDefinition(
            "RTCM1127", 1127, "Appendix 2", "RTCM1127", "RTCM1127", False
        ),
    }
)
# The R1.15 text lists only ASCII syntax for L1SMT. A receiver accepted the
# binary commands with ONCHANGED, and documented binary layouts are available.
RAW_CORRECTION_LOGS: frozenset[str] = frozenset()
R115_LOGS: Mapping[str, LogDefinition] = MappingProxyType(
    {
        "APPPNAV": LogDefinition(
            "APPPNAV", 1457, "7.5.11", "APPPNAVA", "APPPNAVB", False
        ),
        "LBANDAUTH": LogDefinition(
            "LBANDAUTH", 1468, "7.5.50", "LBANDAUTHA", "LBANDAUTHB", False
        ),
        "LBANDBEAM": LogDefinition(
            "LBANDBEAM", 1466, "7.5.51", "LBANDBEAMA", "LBANDBEAMB", False
        ),
        "LBANDTRACKSTATUS": LogDefinition(
            "LBANDTRACKSTATUS",
            1467,
            "7.5.52",
            "LBANDTRACKSTATUSA",
            "LBANDTRACKSTATUSB",
            False,
        ),
        "LBANDUSERDATA": LogDefinition(
            "LBANDUSERDATA", 1469, "7.5.53", "LBANDUSERDATAA", "LBANDUSERDATAB", True
        ),
        "L1SMT47": LogDefinition(
            "L1SMT47", 60234, "7.5.54", "L1SMT47A", "L1SMT47B", True
        ),
        "L1SMT48": LogDefinition(
            "L1SMT48", 60236, "7.5.55", "L1SMT48A", "L1SMT48B", True
        ),
        "L1SMT49": LogDefinition(
            "L1SMT49", 60238, "7.5.56", "L1SMT49A", "L1SMT49B", True
        ),
        "L1SMT50": LogDefinition(
            "L1SMT50", 60240, "7.5.57", "L1SMT50A", "L1SMT50B", True
        ),
        "L6MDCTYPE1": LogDefinition(
            "L6MDCTYPE1", 2325, "7.5.58", "L6MDCTYPE1A", "L6MDCTYPE1B", True
        ),
        "L6MDCTYPE2": LogDefinition(
            "L6MDCTYPE2", 2326, "7.5.59", "L6MDCTYPE2A", "L6MDCTYPE2B", True
        ),
        "L6MDCTYPE3": LogDefinition(
            "L6MDCTYPE3", 2327, "7.5.60", "L6MDCTYPE3A", "L6MDCTYPE3B", True
        ),
        "L6MDCTYPE4": LogDefinition(
            "L6MDCTYPE4", 2328, "7.5.61", "L6MDCTYPE4A", "L6MDCTYPE4B", True
        ),
        "L6MDCTYPE5": LogDefinition(
            "L6MDCTYPE5", 2329, "7.5.62", "L6MDCTYPE5A", "L6MDCTYPE5B", True
        ),
        "L6MDCTYPE7": LogDefinition(
            "L6MDCTYPE7", 2330, "7.5.63", "L6MDCTYPE7A", "L6MDCTYPE7B", True
        ),
        "RPPPDOP": LogDefinition(
            "RPPPDOP", 1028, "7.5.77", "RPPPDOPA", "RPPPDOPB", False
        ),
        "RPPPNAV": LogDefinition(
            "RPPPNAV", 1027, "7.5.80", "RPPPNAVA", "RPPPNAVB", False
        ),
        "RTKSTATUS2": LogDefinition(
            "RTKSTATUS2", 691, "7.5.88", "RTKSTATUS2A", "RTKSTATUS2B", False
        ),
    }
)
LOGS = MappingProxyType(dict(LOGS) | dict(RTCM_LOGS) | dict(R115_LOGS))

WIRE_LOGS: Mapping[str, LogDefinition] = MappingProxyType(
    {
        name: definition
        for definition in LOGS.values()
        for name in (
            definition.name,
            definition.ascii_command,
            definition.binary_command,
        )
        if name is not None
    }
)
