from math import inf, nan

import pytest

from conftest import acknowledgement
from um982py.commands import configuration, logging, modes, queries, system
from um982py.commands.core import action, number, token
from um982py.commands.types import (
    Constellation,
    NmeaVersion,
    Parity,
    Port,
    ResetTarget,
    RoverDynamics,
    Trigger,
)
from um982py.messages import CommandResponse, Sentence, TextLine


@pytest.mark.parametrize(
    "text",
    [
        "",
        " RESET",
        "RESET ",
        "RESET\r\nFRESET",
        "CONFIG;FRESET",
        "RÉSET",
        "$RESET*55",
        "$RESET",
        "#RESET",
        "A\0B",
    ],
)
def test_invalid_command(text: str) -> None:
    with pytest.raises(ValueError):
        action(text)


@pytest.mark.parametrize("value", [nan, inf, -inf, True, -91, 91])
def test_invalid_number(value: float) -> None:
    with pytest.raises(ValueError):
        number(value, -90, 90)


def test_action_and_checksum() -> None:
    command = system.reset()
    assert command.encode() == b"RESET\r\n"
    assert command.encode(checksummed=True) == b"$RESET*55\r\n"
    assert command.matches(CommandResponse("reset", "OK", b""))
    assert not command.matches(TextLine(b""))
    assert command.decode(CommandResponse("RESET", "OK", b"")).accepted
    with pytest.raises(TypeError):
        command.decode(TextLine(b""))
    with pytest.raises(ValueError):
        token("A B")


def test_configuration_builders() -> None:
    assert (
        configuration.serial_port(
            Port.COM2, 460800, parity=Parity.EVEN, stop_bits=2
        ).text
        == "CONFIG COM2 460800 8 E 2"
    )
    assert configuration.nmea_version(NmeaVersion.V411).text == "CONFIG NMEA0183 V411"
    assert configuration.signal_group(3, 6).text == "CONFIG SIGNALGROUP 3 6"
    assert configuration.elevation_mask(10.5).text == "MASK 10.5"
    assert configuration.constellation(Constellation.GPS).text == "UNMASK GPS"
    assert (
        configuration.constellation(Constellation.BDS, enabled=False).text == "MASK BDS"
    )
    assert configuration.command_checksums(enabled=True).text == "CONFIG CMDFORMAT 1"
    with pytest.raises(ValueError):
        configuration.serial_port(Port.COM1, 12345)
    with pytest.raises(ValueError):
        configuration.signal_group(1, 1)


def test_current_signal_group_query_and_model() -> None:
    from um982py.commands.configuration import SIGNAL_GROUP_BANDS, SignalGroup
    from um982py.messages.frames import Sentence

    query = configuration.current_signal_group()
    assert query.text == "CONFIG"
    record = Sentence("CONFIG", ("SIGNALGROUP", "CONFIG SIGNALGROUP 3 6"), b"raw")
    assert query.matches(record)
    assert not query.matches(Sentence("CONFIG", ("OTHER",), b"raw"))
    group = query.decode(record)
    assert isinstance(group, SignalGroup)
    assert (group.master, group.slave) == (3, 6)
    assert "BDS" in group.master_bands and "20 Hz" in group.master_bands
    assert "GAL E1/E5b" in group.slave_bands
    # Single-argument listings use slave 0.
    single = SignalGroup.from_message(
        Sentence("CONFIG", ("SIGNALGROUP", "CONFIG SIGNALGROUP 4"), b"raw")
    )
    assert (single.master, single.slave) == (4, 0)
    assert set(SIGNAL_GROUP_BANDS) == set(range(11))
    with pytest.raises(ValueError):
        SignalGroup.from_message(Sentence("CONFIG", ("MODE",), b"raw"))
    with pytest.raises(ValueError):
        SignalGroup.from_message(
            Sentence("CONFIG", ("SIGNALGROUP", "CONFIG SIGNALGROUP"), b"raw")
        )


def test_mode_and_system_builders() -> None:
    assert modes.rover(RoverDynamics.UAV).text == "MODE ROVER UAV"
    assert modes.heading().text == "MODE HEADING"
    assert modes.heading(secondary=True).text == "MODE HEADING2"
    assert modes.base_position(40.5, 11.5, 10).text == "MODE BASE 40.5 11.5 10"
    assert (
        modes.base_position(40.5, 11.5, 10, station_id=2).text
        == "MODE BASE 2 40.5 11.5 10"
    )
    with pytest.raises(ValueError):
        modes.base_position(0, 0, 0, station_id=4096)
    assert system.reset(ResetTarget.EPHEMERIS).text == "RESET EPHEM"
    assert system.factory_reset().text == "FRESET"
    assert system.save_configuration().text == "SAVECONFIG"


def test_logging_builders_and_matchers() -> None:
    assert logging.output("GPGGA", 0.1, port=Port.COM2).text == "GPGGA COM2 0.1"
    assert logging.output("GPSIONA", Trigger.ON_CHANGED).text == "GPSIONA ONCHANGED"
    assert logging.stop().text == "UNLOG"
    assert logging.stop("GPGGA", port=Port.COM1).text == "UNLOG COM1 GPGGA"
    assert logging.request("GPGGA").matches(Sentence("GNGGA", (), b""))
    assert not logging.request("GPGGA").matches(TextLine(b""))
    with pytest.raises(ValueError):
        logging.request("UNKNOWNB")


def test_query_selectors() -> None:
    assert queries.configuration().matches(Sentence("CONFIG", (), b""))
    assert queries.masks().matches(Sentence("CONFIG", ("MASK", "MASK 5"), b""))
    assert not queries.masks().matches(Sentence("CONFIG", ("COM1",), b""))
    assert queries.fix().text == "GPGGA"
    assert queries.heading().text == "GPTHS"
    assert acknowledgement("RESET").startswith(b"$command")


def test_rtcm_clock_drift_config() -> None:
    assert configuration.rtcm_clock_drift().text == "CONFIG RTCMCLOCKDRIFT ENABLE"
    assert (
        configuration.rtcm_clock_drift(enabled=False).text
        == "CONFIG RTCMCLOCKDRIFT DISABLE"
    )


def test_tp_ion_use_config() -> None:
    assert configuration.tp_ion_use().text == "CONFIG TPIONUSE ENABLE"
    assert configuration.tp_ion_use(enabled=False).text == "CONFIG TPIONUSE DISABLE"


def test_mask_cn0_command() -> None:
    from um982py.commands import masking

    assert masking.cn0(25.0).text == "MASK CN0 25"
    assert masking.cn0(25.0, signal="L1").text == "MASK CN0 25 L1"
    assert masking.cn0(30.0, rtcm=True).text == "MASK RTCMCN0 30"
    assert masking.cn0(30.0, signal="L5", rtcm=True).text == "MASK RTCMCN0 30 L5"


def test_smooth_heading_with_level() -> None:
    assert configuration.smooth_heading(10).text == "CONFIG SMOOTH HEADING 10"
    assert (
        configuration.smooth_heading(10, level_epochs=5).text
        == "CONFIG SMOOTH HEADING 10 5"
    )
    assert configuration.smooth_heading(10, pitch_epochs=5).text == (
        "CONFIG SMOOTH HEADING 10 5"
    )
    with pytest.raises(ValueError):
        configuration.smooth_heading(10, level_epochs=5, pitch_epochs=6)
    with pytest.raises(ValueError):
        configuration.smooth_heading(10, pitch_epochs=101)


def test_rover_default() -> None:
    assert modes.rover_default().text == "MODE ROVER"
    assert modes.rover().text == "MODE ROVER SURVEY"


def test_ppp_services_and_exclusive_mode() -> None:
    assert configuration.ppp(service="L6MDCPPP").text == "CONFIG PPP ENABLE L6MDCPPP"
    assert (
        configuration.ppp(service="E6-HAS", only=True).text
        == "CONFIG PPP ENABLE E6-HAS ONLY"
    )
    assert (
        configuration.ppp(service="B2B-PPP", only=True).text
        == "CONFIG PPP ENABLE B2B-PPP ONLY"
    )
    with pytest.raises(ValueError):
        configuration.ppp(service="AUTO", only=True)
    with pytest.raises(ValueError):
        configuration.ppp(enabled=False, only=True)


def test_um982_commands() -> None:
    assert configuration.sbas(service="QZSS").text == "CONFIG SBAS ENABLE QZSS"
    assert (
        configuration.receiver_input_type("COM2", "RTCM").text
        == "CONFIG RXTYPE COM2 RTCM"
    )
    assert (
        configuration.one_satellite_tracking(enabled=False).text
        == "CONFIG ONESATTRK DISABLE"
    )
    assert modes.rover(RoverDynamics.RACING).text == "MODE ROVER RACING"
    assert configuration.pps(user_delay_ns=100_000_000).text.endswith(" 0 100000000")
    with pytest.raises(ValueError):
        configuration.pps(user_delay_ns=100_000_001)
    with pytest.raises(ValueError):
        configuration.receiver_input_type("COM1", "RTCM")  # type: ignore[arg-type]


def test_l_band_config() -> None:
    assert configuration.l_band().text == "CONFIG LBAND ENABLE AUTO"
    assert configuration.l_band(beam_id=3).text == "CONFIG LBAND ENABLE BEAMID 3"
    assert configuration.l_band(reliability=2).text == "CONFIG LBAND RELIABILITY 2"
    assert configuration.l_band(datum="WGS84").text == "CONFIG LBAND DATUM WGS84"
    assert configuration.l_band(timeout=300).text == "CONFIG LBAND TIMEOUT 300"
    assert configuration.l_band(timeout=0).text == "CONFIG LBAND TIMEOUT 0"
    assert configuration.l_band(enabled=False).text == "CONFIG LBAND DISABLE"
    with pytest.raises(ValueError):
        configuration.l_band(beam_id=8)
    with pytest.raises(ValueError):
        configuration.l_band(reliability=0)
    with pytest.raises(ValueError):
        configuration.l_band(timeout=89)
    with pytest.raises(ValueError):
        configuration.l_band(enabled=False, beam_id=1)
    with pytest.raises(ValueError, match="one L-band action"):
        configuration.l_band(beam_id=1, timeout=120)
    with pytest.raises(ValueError):
        configuration.l_band(timeout=False)  # type: ignore[arg-type]


def test_ppp_rtk_config() -> None:
    assert configuration.ppp_rtk().text == "CONFIG PPPRTK ENABLE"
    assert configuration.ppp_rtk(service="L6CLAS").text == "CONFIG PPPRTK ENABLE L6CLAS"
    assert configuration.ppp_rtk(timeout=100).text == "CONFIG PPPRTK TIMEOUT 100"
    assert configuration.ppp_rtk(timeout=0).text == "CONFIG PPPRTK TIMEOUT 0"
    assert (
        configuration.ppp_rtk(convergence=(50, 80)).text
        == "CONFIG PPPRTK CONVERGE 50 80"
    )
    assert configuration.ppp_rtk(enabled=False).text == "CONFIG PPPRTK DISABLE"
    with pytest.raises(ValueError):
        configuration.ppp_rtk(service="UNKNOWN")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        configuration.ppp_rtk(timeout=601)
    with pytest.raises(ValueError):
        configuration.ppp_rtk(enabled=False, service="L6CLAS")
    with pytest.raises(ValueError, match="one PPPRTK action"):
        configuration.ppp_rtk(service="L6CLAS", timeout=120)
    with pytest.raises(ValueError):
        configuration.ppp_rtk(timeout=False)  # type: ignore[arg-type]


def test_r115_configuration_bounds() -> None:
    assert configuration.velocity_std_threshold(horizontal=10, vertical=1000).text == (
        "CONFIG VELSTDTHD ENABLE 10 1000"
    )
    for value in (9, 1001, 10.5, True):
        with pytest.raises(ValueError):
            configuration.velocity_std_threshold(horizontal=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        configuration.heading_length(20, 0)
    with pytest.raises(ValueError):
        configuration.ionosphere_level(0.55)
    with pytest.raises(ValueError):
        configuration.ionosphere_model("BD3GIM")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        configuration.ionosphere_model("GALNTCM")  # type: ignore[arg-type]


def test_signal_group_descriptions_match_r115() -> None:
    bands = configuration.SIGNAL_GROUP_BANDS
    assert "L1S" in bands[1]
    assert "B2a" in bands[5]
    assert "GLO" not in bands[6]
    assert 10 in bands


def test_standalone_timeout_r115() -> None:
    assert (
        configuration.standalone_timeout(1800).text == "CONFIG STANDALONE TIMEOUT 1800"
    )
    assert (
        configuration.standalone_timeout(86400).text
        == "CONFIG STANDALONE TIMEOUT 86400"
    )
    for value in (1799, 86401, 1800.5, True):
        with pytest.raises(ValueError):
            configuration.standalone_timeout(value)  # type: ignore[arg-type]


def test_documented_configuration_keeps_experimental_imports() -> None:
    from um982py.experimental import configuration as experimental

    assert configuration.anti_spoof().text == "CONFIG ANTISPOOF ENABLE"
    assert configuration.anti_spoof(enabled=False).text == "CONFIG ANTISPOOF DISABLE"
    assert configuration.rtcm_output_mode("BASE").text == "CONFIG RTCMOUTPUT BASE"
    assert (
        configuration.ionosphere_level(enabled=False).text == "CONFIG IONLEVEL DISABLE"
    )
    assert configuration.ionosphere_level(0.5).text == "CONFIG IONLEVEL 0.5"
    assert configuration.pvt_reliability(1, 2, 3).text == "CONFIG PVT RELIABILITY 1 2 3"
    assert experimental.anti_spoof is configuration.anti_spoof
    assert experimental.rtcm_output_mode is configuration.rtcm_output_mode
    assert experimental.ionosphere_level is configuration.ionosphere_level
    assert experimental.pvt_reliability is configuration.pvt_reliability


def test_integer_only_configuration() -> None:
    from typing import Literal, cast

    with pytest.raises(ValueError):
        configuration.serial_port(Port.COM1, 115200, stop_bits=cast(Literal[1, 2], 3))
    with pytest.raises(ValueError):
        configuration.signal_group(True, 0)
    with pytest.raises(ValueError):
        modes.base_position(0, 0, 0, station_id=True)
