from collections.abc import Callable
from dataclasses import replace
from math import inf, nan
from typing import Literal, cast

import pytest

from conftest import FIXTURES, ReplayTransport
from test_extended_logs import captured
from um982py import Receiver
from um982py.commands.core import Command, action
from um982py.errors import CommandRejected, ProtocolError
from um982py.experimental import FirmwareLog, FirmwareSwitch
from um982py.experimental import configuration as config
from um982py.messages import AsciiMessage, BinaryMessage, CommandResponse


@pytest.mark.parametrize("setting", list(FirmwareSwitch))
def test_firmware_switches(setting: FirmwareSwitch) -> None:
    assert setting.configure(enabled=True).text == f"CONFIG {setting.value} ENABLE"
    assert setting.configure(enabled=False).text == f"CONFIG {setting.value} DISABLE"
    for value in (1, "ENABLE", None):
        with pytest.raises(ValueError):
            setting.configure(enabled=cast(bool, value))


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_antispoof_levels(level: int) -> None:
    assert config.anti_spoof(level=level).text == f"CONFIG ANTISPOOF ENABLE {level}"
    assert config.anti_spoof().text == "CONFIG ANTISPOOF ENABLE"
    assert config.anti_spoof(enabled=False).text == "CONFIG ANTISPOOF DISABLE"
    with pytest.raises(ValueError):
        config.anti_spoof(enabled=False, level=level)


@pytest.mark.parametrize("level", [0, 5, True, 1.5])
def test_antispoof_bad_levels(level: int) -> None:
    with pytest.raises(ValueError):
        config.anti_spoof(level=level)


def test_msm_is_discrete_not_a_range() -> None:
    for value in (32, 64):
        assert config.msm(cast(Literal[32, 64], value)).text == f"CONFIG MSM {value}"
    for value in (31, 33, 48, 63, 65, True, 32.0):
        with pytest.raises(ValueError):
            config.msm(cast(Literal[32, 64], value))


def test_secondary_heading_and_rtcm_modes() -> None:
    for mode in ("STATIC", "LOWDYNAMIC", "TRACTOR", "FIXLENGTH", "VARIABLELENGTH"):
        assert config.secondary_heading(mode).text == f"CONFIG HEADING2 {mode}"
    assert config.rtk_ifc("AUTO").text == "CONFIG RTKIFC AUTO"
    assert config.rtcm_output_mode("BASE").text == "CONFIG RTCMOUTPUT BASE"
    for factory in (config.secondary_heading, config.rtk_ifc, config.rtcm_output_mode):
        with pytest.raises(ValueError):
            factory("BAD\r\nRESET")


@pytest.mark.parametrize(
    "factory,low,high",
    [
        (config.base_bias, 50, 800),
        (config.matched_satellites, 0, 15),
        (config.tracking_mode, 0, 1),
    ],
)
def test_integer_setting_boundaries(
    factory: Callable[[int], Command[CommandResponse]],
    low: int,
    high: int,
) -> None:
    for value in (low, high):
        assert factory(value).text.endswith(f" {value}")
    for value in (low - 1, high + 1, True, float(low)):
        with pytest.raises(ValueError):
            factory(cast(int, value))
    # Avoid the mutating bare MATCHEDSATS command.
    assert config.matched_satellites().text == "CONFIG MATCHEDSATS 8"


def test_base_observation_filter_combinations() -> None:
    assert config.base_observation_filter().text == "CONFIG BASEOBSFILTER ENABLE"
    assert config.base_observation_filter(enabled=False).text.endswith("DISABLE")
    assert config.base_observation_filter(first=0).text.endswith("ENABLE 0")
    assert config.base_observation_filter(first=12.5, second=60).text.endswith(
        "12.5 60"
    )
    with pytest.raises(ValueError):
        config.base_observation_filter(second=10)
    with pytest.raises(ValueError):
        config.base_observation_filter(enabled=False, first=10)
    for value in (-1, 61, nan, inf, True):
        with pytest.raises(ValueError):
            config.base_observation_filter(first=value)
        with pytest.raises(ValueError):
            config.base_observation_filter(first=10, second=value)


def test_ionosphere_level_boundaries() -> None:
    assert config.ionosphere_level().text == "CONFIG IONLEVEL AUTO"
    for value in (0.5, 1.2, 3):
        assert config.ionosphere_level(value).text.endswith(f" {value:g}")
    for value in (0.49, 3.01, nan, inf, True):
        with pytest.raises(ValueError):
            config.ionosphere_level(value)


@pytest.mark.parametrize(
    "topic",
    [
        "MSM",
        "TRACKMODE",
        "MCPUIDLE",
        "RTK B1CB2A",
        "BASERANGE B1CB2A",
        "BD3",
        "TPIONUSE",
        "RTCMOUTPUT",
        "BASEOBSFILTER",
        "IONLEVEL",
        "IONFACTOR",
    ],
)
def test_missing_arguments_are_errors_not_setting_queries(topic: str) -> None:
    text = f"CONFIG {topic}"
    raw = (
        FIXTURES / "captures-features" / (text.replace(" ", "_") + ".bin")
    ).read_bytes()
    transport = ReplayTransport({(text + "\r\n").encode(): raw})
    with (
        Receiver(transport) as receiver,
        pytest.raises(CommandRejected, match="MISSING FIELD"),
    ):
        receiver.execute(action(text))


def test_antenna_and_spoof_records() -> None:
    a = FirmwareLog.ANTENNA.decode(captured(FirmwareLog.ANTENNA, False))
    b = FirmwareLog.ANTENNA.decode(captured(FirmwareLog.ANTENNA, True))
    assert a["status_1"] == a["status_2"] == "WORK"
    assert b["status_1"] == b["status_2"] == 5
    spoof = FirmwareLog.SPOOFINFO.decode(captured(FirmwareLog.SPOOFINFO, True))
    assert spoof.integer("spoof_indicator") == 0
    assert spoof.integer("field_21") == 0
    message = captured(FirmwareLog.SPOOFINFO, False)
    assert isinstance(message, AsciiMessage)
    for bad in ("not_hex", "10000000000000000"):
        with pytest.raises(ProtocolError):
            FirmwareLog.SPOOFINFO.decode(
                replace(
                    message, fields=(*message.fields[:20], bad, *message.fields[21:])
                )
            )


def test_doppler_logs_have_both_velocity_deviations() -> None:
    for log in (FirmwareLog.DOPPVEL, FirmwareLog.DOPPVELH):
        message = captured(log, True)
        assert isinstance(message, BinaryMessage) and len(message.payload) == 48
        body = log.decode(message)
        assert body.real("horspd_std") >= 0
        assert body.real("verspd_std") >= 0
        with pytest.raises(ProtocolError):
            log.decode(replace(message, payload=message.payload[:44]))
