import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from conftest import FIXTURES, ascii_message, rtcm
from test_protocol import binary
from um982py.commands import Log, assistance, masking, modes, queries
from um982py.commands import configuration as c
from um982py.commands.catalog import LOGS, RTCM_LOGS
from um982py.commands.core import Command
from um982py.commands.types import (
    Constellation,
    NmeaVersion,
    Port,
    RoverDynamics,
    Trigger,
)
from um982py.commands.validation import integer, option, text
from um982py.messages import CommandResponse, LogListMessage
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import parse_binary, parse_rtcm

CASES: list[tuple[str, Callable[[], Command[CommandResponse]], str]] = [
    ("4.2", lambda: c.serial_port(Port.COM1, 115200), "CONFIG COM1 115200 8 N 1"),
    ("4.3", lambda: c.pps(), "CONFIG PPS ENABLE GPS POSITIVE 500000 1000 0 0"),
    ("4.4", lambda: c.undulation(9.7), "CONFIG UNDULATION 9.7"),
    ("4.5", lambda: c.dgps_timeout(100), "CONFIG DGPS TIMEOUT 100"),
    ("4.6", lambda: c.rtk_timeout(60), "CONFIG RTK TIMEOUT 60"),
    ("4.6", lambda: c.rtk_reliability(3, 1), "CONFIG RTK RELIABILITY 3 1"),
    ("4.6", lambda: c.rtk_cn0_threshold(True), "CONFIG RTK CN0THD 1"),
    ("4.6", lambda: c.rtk_multipath_threshold(True), "CONFIG RTK MMPL 1"),
    ("4.6", c.rtk_defaults, "CONFIG RTK USER_DEFAULTS"),
    ("4.6", c.rtk_reset, "CONFIG RTK RESET"),
    ("4.6", c.rtk_disable, "CONFIG RTK DISABLE"),
    ("4.7", c.standalone, "CONFIG STANDALONE ENABLE"),
    ("4.8", lambda: c.heading_mode("FIXLENGTH"), "CONFIG HEADING FIXLENGTH"),
    ("4.8", lambda: c.heading_length(20, 3), "CONFIG HEADING LENGTH 20 3"),
    ("4.8", lambda: c.heading_reliability(3), "CONFIG HEADING RELIABILITY 3"),
    ("4.9", lambda: c.heading_offset(90, 45), "CONFIG HEADING OFFSET 90 45"),
    ("4.10", c.sbas, "CONFIG SBAS ENABLE AUTO"),
    ("4.10", lambda: c.sbas_timeout(600), "CONFIG SBAS TIMEOUT 600"),
    ("4.11", lambda: c.event(guard_ms=10), "CONFIG EVENT ENABLE POSITIVE 10"),
    ("4.12", lambda: c.event2(guard_ms=10), "CONFIG EVENT2 ENABLE POSITIVE 10"),
    ("4.13", lambda: c.smooth_rtk_height(10), "CONFIG SMOOTH RTKHEIGHT 10"),
    ("4.13", lambda: c.smooth_heading(10), "CONFIG SMOOTH HEADING 10"),
    ("4.13", c.smooth_velocity, "CONFIG SMOOTH PSRVEL ENABLE"),
    ("4.14", c.mmp, "CONFIG MMP ENABLE"),
    ("4.15", lambda: c.nmea_version(NmeaVersion.V410), "CONFIG NMEA0183 V410"),
    ("4.16", c.rtcm_b1c_b2a, "CONFIG RTCMB1CB2A ENABLE"),
    ("4.18", c.rtcm_phase_rate, "CONFIG RTCMPHASERATE POSITIVE"),
    ("4.19", c.rtcm_clock_offset, "CONFIG RTCMCLOCKOFFSET ENABLE"),
    ("4.20", c.doppler_prediction, "CONFIG PSRVELDRPOS ENABLE"),
    ("4.21", c.agnss, "CONFIG AGNSS ENABLE"),
    ("4.22", c.ppp, "CONFIG PPP ENABLE B2B-PPP"),
    ("4.22", c.ppp_datum, "CONFIG PPP DATUM PPPORIGINAL"),
    ("4.22", lambda: c.ppp_timeout(120), "CONFIG PPP TIMEOUT 120"),
    ("4.22", lambda: c.ppp_convergence(10, 20), "CONFIG PPP CONVERGE 10 20"),
    ("4.23", c.anti_jam, "CONFIG ANTIJAM AUTO"),
    ("4.24", lambda: c.signal_group(3, 6), "CONFIG SIGNALGROUP 3 6"),
    ("4.25", lambda: c.antenna_delta(1.521), "CONFIG ANTENNADELTAHEN 1.521 0 0"),
    ("4.26", lambda: c.authorization("0x123:ABCD"), "CONFIG AUTHCODE 0x123:ABCD"),
    ("4.27", lambda: c.algorithm_reset("HEADING"), "CONFIG ALGRESET HEADING"),
    ("4.28", c.ionosphere_model, "CONFIG IONMODE GPSK8"),
    (
        "4.29",
        lambda: c.base_antenna_model("HXCCGX601A HXCS", "62815", 1, "USER"),
        'CONFIG BASEANTENNAMODEL "HXCCGX601A HXCS" 62815 1 USER',
    ),
    ("4.30", lambda: c.pvt_algorithm("MULTI"), "CONFIG PVTALG MULTI"),
    ("4.31", c.position_bias, "CONFIG PSRPOSBIAS ENABLE"),
    ("4.34", lambda: c.log_sequence(1), "CONFIG LOGSEQ 1"),
    ("4.37", c.rtcm_decode_auto, "CONFIG RTCMDECAUTO ENABLE"),
    ("4.38", c.all_ephemerides, "CONFIG ALLEPHRTCM ENABLE"),
    (
        "4.39",
        lambda: c.velocity_std_threshold(horizontal=120, vertical=120),
        "CONFIG VELSTDTHD ENABLE 120 120",
    ),
    ("4.40", c.rtk_assists_ppp, "CONFIG RTKASITPPP ENABLE"),
    ("4.41", lambda: c.command_checksums(enabled=True), "CONFIG CMDFORMAT 1"),
]


@pytest.mark.parametrize(
    "section,factory,expected",
    CASES,
    ids=[f"{s}:{e.split()[1:3]}" for s, _, e in CASES],
)
def test_configuration_examples(
    section: str, factory: Callable[[], Command[CommandResponse]], expected: str
) -> None:
    assert factory().text == expected
    assert factory().encode() == (expected + "\r\n").encode()
    assert section.startswith("4.")


def test_all_configuration_sections_are_covered() -> None:
    sections = {s for s, _, _ in CASES} | {"4.1"}
    assert sections == {f"4.{i}" for i in range(1, 42) if i not in (17, 32, 33, 35, 36)}
    assert queries.configuration().text == "CONFIG"


@pytest.mark.parametrize("log", list(Log), ids=lambda log: log.value)
def test_all_documented_logs(log: Log) -> None:
    definition = log.definition
    interval = Trigger.ON_CHANGED if definition.changed_only else 1
    assert log.output(
        interval, port=Port.COM2
    ).text == definition.ascii_command + " COM2 " + str(interval)
    assert log.stop().text == "UNLOG " + definition.ascii_command
    if definition.changed_only:
        with pytest.raises(ValueError):
            log.request()
        with pytest.raises(ValueError):
            log.output(1)
    else:
        request = log.request()
        if definition.name in RTCM_LOGS:
            assert request.matches(
                parse_rtcm(rtcm((definition.message_id << 4).to_bytes(2, "big")))
            )
        elif log is Log.UNILOGLIST:
            frames = StreamDecoder(strict=True).feed(
                b"#UNILOGLIST,98,GPS,FINE,2400,123000,2400,0,18,1;\n"
                b"< 1\n< GNGGA COM1 1\n"
            )
            message = next(m for m in frames if isinstance(m, LogListMessage))
            assert request.matches(message) and not message.checksum_verified
        else:
            assert request.matches(
                parse_ascii(ascii_message(definition.ascii_command, "1,2"))
            )
    if definition.binary_command is None:
        with pytest.raises(ValueError):
            log.wire_name(binary=True)
    else:
        assert log.output(interval, binary=True).text.startswith(
            definition.binary_command
        )
        if not definition.changed_only:
            request = log.request(binary=True)
            if definition.name not in RTCM_LOGS:
                assert request.matches(parse_binary(binary(b"", definition.message_id)))


def test_catalog_matches_manual_inventory() -> None:
    reference = json.loads((FIXTURES / "reference-r1.4.json").read_text())
    assert len(reference["logs"]) == 79
    for item in reference["logs"]:
        definition = LOGS[item["name"]]
        assert (definition.section, definition.message_id) == (
            item["section"],
            item["message_id"],
        )
        for example in item["examples"]:
            head = example.split()[0]
            assert head in (
                definition.name,
                definition.ascii_command,
                definition.binary_command,
            )
    assert sum(d.section == "Appendix 2" for d in LOGS.values()) == 29
    assert Log.EVENTFLAG.definition.message_id == 312
    assert Log.EVENTSLN.definition.message_id == 311


def test_mode_mask_and_assistance_examples() -> None:
    assert modes.base().text == "MODE BASE"
    assert modes.base(1).text == "MODE BASE 1"
    assert modes.base_survey(60, distance=5).text == "MODE BASE TIME 60 5"
    assert modes.base_survey(60, station_id=1).text == "MODE BASE 1 TIME 60"
    assert modes.base_ecef(-2160489.0276, 4383620.1006, 4084738.111).text.startswith(
        "MODE BASE -2160489"
    )
    assert (
        modes.rover(RoverDynamics.SURVEY, profile="MOW").text == "MODE ROVER SURVEY MOW"
    )
    assert (
        modes.rover(RoverDynamics.UAV, profile="HIGHDYN").text
        == "MODE ROVER UAV HIGHDYN"
    )
    assert modes.heading2().text == "MODE HEADING2"
    assert modes.heading2("TRACTOR").text == "MODE HEADING2 TRACTOR"
    assert masking.frequency("E5a").text == "MASK E5A"
    assert masking.frequency("B1", enabled=True).text == "UNMASK B1"
    assert masking.satellite(Constellation.GPS, 10).text == "MASK GPS PRN 10"
    assert (
        masking.satellite(Constellation.GLONASS, 38, enabled=True).text
        == "UNMASK GLO PRN 38"
    )
    assert masking.cn0(30).text == "MASK CN0 30"
    assert masking.cn0(30, signal="L1", rtcm=True).text == "MASK RTCMCN0 30 L1"
    assert (
        assistance.position(40 + 2.229934 / 60, 116 + 18.096855 / 60, 37.254).encode()
        == b"$AIDPOS,4002.229934,N,11618.096855,E,37.254\r\n"
    )
    assert (
        assistance.time(datetime(2021, 12, 3, 15, 2, 36, 400000, tzinfo=UTC)).encode()
        == b"$AIDTIME,2021,12,3,15,2,36,400,18\r\n"
    )
    assert (
        assistance.position(-90, -180, 0)
        .encode()
        .startswith(b"$AIDPOS,9000.000000,S,18000.000000,W")
    )
    local = datetime(2021, 12, 3, 16, 2, 36, tzinfo=timezone(timedelta(hours=1)))
    assert assistance.time(local).text == "AIDTIME,2021,12,3,15,2,36,0,18"
    assert assistance.time_fields(2016, 12, 31, 23, 59, 60, 0).text.endswith(",60,0,18")


def test_configuration_variants() -> None:
    commands = [
        c.pps(mode="DISABLE"),
        c.undulation(),
        c.rtk_reliability(4),
        c.standalone(enabled=False),
        c.standalone(wait_seconds=40),
        c.standalone(coordinates=(40.113452, 114.212234, 57.23)),
        c.heading_length(),
        c.sbas(enabled=False),
        c.sbas_timeout(0),
        c.event(enabled=False),
        c.event2(enabled=False),
        c.mmp(enabled=False),
        c.smooth_velocity(enabled=False),
        c.ppp(enabled=False),
        c.ppp_timeout(0),
        c.velocity_std_threshold(enabled=False),
        c.signal_group(1, product="UM980"),
        c.signal_group(9, product="UB9A0"),
        c.signal_group(7),
    ]
    assert len({command.text for command in commands}) == len(commands)
    assert all(command.encode().endswith(b"\r\n") for command in commands)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: c.pps(width_us=1000000),
        lambda: c.pps(rf_delay_ns=32768),
        lambda: c.event(guard_ms=1),
        lambda: c.undulation(1001),
        lambda: c.rtk_reliability(0),
        lambda: c.standalone(wait_seconds=2),
        lambda: c.standalone(coordinates=(0, 0, 0), wait_seconds=5),
        lambda: c.standalone(enabled=False, wait_seconds=5),
        lambda: c.heading_length(10),
        lambda: c.heading_length(tolerance_cm=10),
        lambda: c.heading_offset(181, 0),
        lambda: c.sbas_timeout(1),
        lambda: c.ppp_timeout(181),
        lambda: c.antenna_delta(7),
        lambda: c.base_antenna_model("a" * 32),
        lambda: c.authorization("x\r\nFRESET"),
        lambda: integer(True, 0, 1),
        lambda: option("INVALID", ("AUTO",)),
        lambda: text("a b"),
        lambda: text("bad*"),
        lambda: modes.base_ecef(0, 1, 2),
        lambda: modes.rover(RoverDynamics.UAV, profile="MOW"),
        lambda: masking.satellite(Constellation.GPS, 33),
        lambda: assistance.time(datetime(2021, 1, 1)),
        lambda: assistance.time_fields(2021, 2, 30, 0, 0, 0, 0),
        lambda: c.signal_group(1, 1, product="UM980"),
        lambda: c.signal_group(7, True),
    ],
)
def test_reference_validation(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_invalid_boolean_switch() -> None:
    with pytest.raises(ValueError):
        c.mmp(enabled=cast(bool, 1))
    with pytest.raises(ValueError):
        c.ppp_timeout(False)


def test_dollar_sign_in_parameters() -> None:
    assert text("antenna $1", quoted=True) == '"antenna $1"'
