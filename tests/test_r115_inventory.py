"""Keep the supported command and decoder inventory aligned with R1.15."""

import json

import pytest

from conftest import FIXTURES
from um982py import Log
from um982py.commands import Command, masking, queries
from um982py.commands import configuration as config
from um982py.commands.catalog import LOGS, RTCM_LOGS
from um982py.commands.types import NmeaVersion, Port
from um982py.firmware_layouts import LAYOUTS as EXTENDED_LAYOUTS
from um982py.messages import CommandResponse, Message
from um982py.messages.layouts import LAYOUTS
from um982py.messages.nmea import SCHEMAS
from um982py.rtcm import STANDARD_RTCM_TYPES, UNICORE_RTCM_TYPES

REFERENCE = json.loads((FIXTURES / "reference-r1.15.json").read_text())


def test_r115_inventory_covers_all_log_sections() -> None:
    entries = REFERENCE["logs"]
    names = {item["name"] for item in entries}
    assert len(names) == len(entries)
    assert names == (
        LOGS.keys()
        - RTCM_LOGS.keys()
        - {"PPPB2BINFO6", "PPPB2BINFO7", "PPSSTATUS", "SPOOFINFO"}
    )
    sections = {item["section"] for item in entries}
    assert {f"7.5.{n}" for n in range(2, 102)} - {"7.5.10", "7.5.84"} == {
        section for section in sections if section.startswith("7.5.")
    }
    assert {f"7.2.{n}" for n in range(1, 15)} <= sections
    assert {f"7.4.{n}" for n in range(1, 17)} <= sections
    assert {item["section"] for item in REFERENCE["excluded_logs"]} == {"7.5.84"}


@pytest.mark.parametrize("item", REFERENCE["logs"], ids=lambda item: item["name"])
def test_r115_log_has_command_and_decoder(item: dict) -> None:
    log = Log[item["name"]]
    assert log.definition.message_id == item["message_id"]
    assert log.wire_name()
    if item["message_id"] is not None:
        assert log.wire_name(binary=True)
        assert log.value in LAYOUTS.keys() | EXTENDED_LAYOUTS.keys() | {"SATSINFO"}
    elif log is not Log.UNILOGLIST:
        kind = log.value[2:] if log.value.startswith(("GP", "QZ")) else log.value
        if kind.endswith("H"):
            kind = kind[:-1]
        if kind in ("THS2", "HPR2", "ROT2"):
            kind = kind[:-1]
        assert kind in SCHEMAS.keys() | {"GSV"}


def test_rtcm_catalogue_matches_supported_and_private_wire_types() -> None:
    expected = set(REFERENCE["rtcm"])
    assert {log.message_id for log in RTCM_LOGS.values()} == expected
    assert expected == STANDARD_RTCM_TYPES | UNICORE_RTCM_TYPES
    assert STANDARD_RTCM_TYPES.isdisjoint(UNICORE_RTCM_TYPES)


# Each applicable configuration section has an executable wire example.
CONFIGURATION = [
    (1, queries.configuration(), "CONFIG"),
    (2, config.serial_port(Port.COM1, 115200), "CONFIG COM1 115200 8 N 1"),
    (3, config.receiver_input_type("COM2", "RTCM"), "CONFIG RXTYPE COM2 RTCM"),
    (4, config.agnss(), "CONFIG AGNSS ENABLE"),
    (5, config.algorithm_reset("HEADING"), "CONFIG ALGRESET HEADING"),
    (6, config.all_ephemerides(), "CONFIG ALLEPHRTCM ENABLE"),
    (7, config.antenna_delta(1), "CONFIG ANTENNADELTAHEN 1 0 0"),
    (8, config.anti_jam(), "CONFIG ANTIJAM AUTO"),
    (9, config.anti_spoof(), "CONFIG ANTISPOOF ENABLE"),
    (
        10,
        config.base_antenna_model(),
        'CONFIG BASEANTENNAMODEL "ADVNULLANTENNA" a0001 0 NO',
    ),
    (12, config.command_checksums(enabled=True), "CONFIG CMDFORMAT 1"),
    (13, config.dgps_timeout(100), "CONFIG DGPS TIMEOUT 100"),
    (16, config.event(), "CONFIG EVENT ENABLE POSITIVE 4"),
    (17, config.event2(), "CONFIG EVENT2 ENABLE POSITIVE 4"),
    (18, config.heading_mode("FIXLENGTH"), "CONFIG HEADING FIXLENGTH"),
    (19, config.heading_offset(90, 45), "CONFIG HEADING OFFSET 90 45"),
    (20, config.ionosphere_level(), "CONFIG IONLEVEL AUTO"),
    (21, config.ionosphere_model(), "CONFIG IONMODE GPSK8"),
    (22, config.l_band(), "CONFIG LBAND ENABLE AUTO"),
    (23, config.log_sequence(), "CONFIG LOGSEQ 2"),
    (24, config.mmp(), "CONFIG MMP ENABLE"),
    (25, config.nmea_version(NmeaVersion.V411), "CONFIG NMEA0183 V411"),
    (29, config.one_satellite_tracking(), "CONFIG ONESATTRK ENABLE"),
    (30, config.ppp(service="L6MDCPPP", only=True), "CONFIG PPP ENABLE L6MDCPPP ONLY"),
    (31, config.ppp_rtk(service="L6CLAS"), "CONFIG PPPRTK ENABLE L6CLAS"),
    (32, config.pps(), "CONFIG PPS ENABLE GPS POSITIVE 500000 1000 0 0"),
    (33, config.position_bias(), "CONFIG PSRPOSBIAS ENABLE"),
    (34, config.doppler_prediction(), "CONFIG PSRVELDRPOS ENABLE"),
    (35, config.pvt_algorithm("MULTI"), "CONFIG PVTALG MULTI"),
    (36, config.pvt_reliability(2, 2, 2), "CONFIG PVT RELIABILITY 2 2 2"),
    (38, config.rtcm_b1c_b2a(), "CONFIG RTCMB1CB2A ENABLE"),
    (39, config.rtcm_clock_drift(), "CONFIG RTCMCLOCKDRIFT ENABLE"),
    (40, config.rtcm_phase_rate(), "CONFIG RTCMPHASERATE POSITIVE"),
    (41, config.rtcm_clock_offset(), "CONFIG RTCMCLOCKOFFSET ENABLE"),
    (42, config.rtcm_decode_auto(), "CONFIG RTCMDECAUTO ENABLE"),
    (43, config.rtcm_output_mode("BASE"), "CONFIG RTCMOUTPUT BASE"),
    (44, config.rtk_reliability(), "CONFIG RTK RELIABILITY 3"),
    (45, config.rtk_assists_ppp(), "CONFIG RTKASITPPP ENABLE"),
    (47, config.sbas(service="QZSS"), "CONFIG SBAS ENABLE QZSS"),
    (48, config.signal_group(3, 6), "CONFIG SIGNALGROUP 3 6"),
    (49, config.smooth_heading(10, pitch_epochs=20), "CONFIG SMOOTH HEADING 10 20"),
    (50, config.standalone_timeout(3600), "CONFIG STANDALONE TIMEOUT 3600"),
    (51, config.tp_ion_use(), "CONFIG TPIONUSE ENABLE"),
    (52, config.undulation(), "CONFIG UNDULATION AUTO"),
    (53, config.velocity_std_threshold(), "CONFIG VELSTDTHD ENABLE 50 50"),
]


@pytest.mark.parametrize("section,command,expected", CONFIGURATION)
def test_configuration_wire_example(
    section: int, command: Command[Message] | Command[CommandResponse], expected: str
) -> None:
    assert command.text == expected
    assert command.encode() == (expected + "\r\n").encode()


def test_every_configuration_section_is_accounted_for() -> None:
    excluded = {
        11: "BASEBIAS: UM980/UM980C; experimental UM982 support remains separate",
        14: "ETH1: UB9A0/UBD9A0",
        15: "ICOM: UB9A0/UBD9A0",
        26: "NTRIP client: UB9A0/UBD9A0",
        27: "NTRIP server: UB9A0/UBD9A0",
        28: "POSREF: single-antenna products",
        37: "REMOTEANTENNAPCO: single-antenna products",
        46: "SELFANTENNAPCO: single-antenna products",
    }
    sections = [section for section, _, _ in CONFIGURATION]
    assert len(sections) == len(set(sections))
    assert set(sections).isdisjoint(excluded)
    assert set(sections) | set(excluded) == set(range(1, 54))


def test_azimuth_sector_command() -> None:
    assert masking.azimuth(20, 90, 15, 45).encode() == b"MASK AZIMUTH 1 20 90 15 45\r\n"
    assert masking.azimuth(-10, 89.5, 0, 360).text == "MASK AZIMUTH 1 -10 89.5 0 360"


@pytest.mark.parametrize(
    "bounds",
    [
        (-91, 90, 0, 360),
        (0, 91, 0, 360),
        (20, 10, 0, 360),
        (0, 90, -1, 360),
        (0, 90, 0, 361),
        (0, 90, 350, 10),
        (0, 90, 10, 10),
        (0, 0, 0, 360),
        (True, 90, 0, 360),
        (0, float("inf"), 0, 360),
        (0, 90, float("nan"), 360),
    ],
)
def test_invalid_azimuth_sectors(bounds: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        masking.azimuth(*bounds)
