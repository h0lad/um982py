"""Extended configuration commands."""

from enum import StrEnum
from typing import Literal

from um982py.commands.configuration.corrections import anti_spoof as anti_spoof
from um982py.commands.configuration.corrections import (
    ionosphere_level as ionosphere_level,
)
from um982py.commands.configuration.corrections import (
    rtcm_output_mode as rtcm_output_mode,
)
from um982py.commands.configuration.positioning import (
    pvt_reliability as pvt_reliability,
)
from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, switch
from um982py.messages import CommandResponse


class FirmwareSwitch(StrEnum):
    """Exposes boolean switches through ``.configure(enabled=...)``."""

    BD3 = "BD3"
    DUALBEST = "DUALBEST"
    MCPUIDLE = "MCPUIDLE"
    RTK_B1CB2A = "RTK B1CB2A"
    BASERANGE_B1CB2A = "BASERANGE B1CB2A"
    SFRTK = "SFRTK"
    BASEBIASCORR = "BASEBIASCORR"
    BESTSATSYNC = "BESTSATSYNC"
    BBL1MASTER = "BBL1MASTER"
    RTCML1MASTER = "RTCML1MASTER"
    VELDRPOS2 = "VELDRPOS2"
    TPIONUSE = "TPIONUSE"
    RTCMCLOCKDRIFT = "RTCMCLOCKDRIFT"
    MVCHECK = "MVCHECK"
    PSRVELDRPOS = "PSRVELDRPOS"

    def configure(self, *, enabled: bool) -> Command[CommandResponse]:
        return switch(self.value, enabled)


def secondary_heading(
    mode: Literal["STATIC", "LOWDYNAMIC", "TRACTOR", "FIXLENGTH", "VARIABLELENGTH"],
) -> Command[CommandResponse]:
    """Select the receiver's HEADING2 mode, whose availability is unverified."""
    return config(
        "HEADING2",
        option(
            mode,
            (
                "STATIC",
                "LOWDYNAMIC",
                "TRACTOR",
                "FIXLENGTH",
                "VARIABLELENGTH",
            ),
        ),
    )


def rtk_ifc(mode: Literal["ENABLE", "DISABLE", "AUTO"]) -> Command[CommandResponse]:
    """Select the raw RTKIFC mode, whose exact effect is unverified."""
    return config("RTKIFC", option(mode, ("ENABLE", "DISABLE", "AUTO")))


def msm(value: Literal[32, 64]) -> Command[CommandResponse]:
    """Select the raw MSM value, where only 32 and 64 pass this parser."""
    integer(value, 32, 64)
    if value not in (32, 64):
        raise ValueError("MSM must be 32 or 64")
    return config("MSM", str(value))


def tracking_mode(value: Literal[0, 1]) -> Command[CommandResponse]:
    """Select TRACKMODE 0 or 1, whose meanings remain unverified."""
    return config("TRACKMODE", integer(value, 0, 1))


def matched_satellites(value: int = 8) -> Command[CommandResponse]:
    """Set the raw MATCHEDSATS value in 0..15, which defaults to 8."""
    return config("MATCHEDSATS", integer(value, 0, 15))


def base_bias(value: int) -> Command[CommandResponse]:
    """Set BASEBIAS in 50..800, whose units and effects are unverified."""
    return config("BASEBIAS", integer(value, 50, 800))


def base_observation_filter(
    *,
    enabled: bool = True,
    first: float | None = None,
    second: float | None = None,
) -> Command[CommandResponse]:
    """Set BASEOBSFILTER with up to two values in 0..60."""
    command = switch("BASEOBSFILTER", enabled)
    if not enabled and (first is not None or second is not None):
        raise ValueError("Disabled BASEOBSFILTER takes no values")
    if second is not None and first is None:
        raise ValueError("A second value requires the first")
    if first is None:
        return command
    values = [number(first, 0, 60)]
    if second is not None:
        values.append(number(second, 0, 60))
    return config("BASEOBSFILTER ENABLE", *values)


def best_position_bias(
    *, enabled: bool = True, threshold: int | None = None
) -> Command[CommandResponse]:
    """Configure the BESTPOS bias threshold in 200..30000, in unverified units."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    if threshold is None:
        return switch("BESTPOSBIAS", enabled)
    if not enabled:
        raise ValueError("Disabled BESTPOSBIAS takes no threshold")
    return config("BESTPOSBIAS ENABLE", integer(threshold, 200, 30000))


def leap_seconds(seconds: int | None = None) -> Command[CommandResponse]:
    """Use an explicit leap-second value (0..64), or disable the override."""
    if seconds is None:
        return config("LEAPSECOND DISABLE")
    return config("LEAPSECOND ENABLE", integer(seconds, 0, 64))


def base_type(manufacturer: str) -> Command[CommandResponse]:
    """Select the base compatibility mode accepted by the receiver."""
    return config(
        "BASETYPE",
        option(
            manufacturer,
            (
                "DISABLE",
                "UNICORE",
                "NOV",
                "LEICA",
                "TRIMBLE",
                "TOPCON",
                "TPS",
                "JAVAD",
                "SEPT",
            ),
        ),
    )


def rtk_elevation_mask(
    degrees: float | None = None,
    *,
    secondary: float | None = None,
    third: float | None = None,
) -> Command[CommandResponse]:
    """Set AUTO or one and three elevation thresholds in 0..90."""
    if degrees is None:
        if secondary is not None or third is not None:
            raise ValueError("AUTO takes no thresholds")
        return config("RTKELEVMASK AUTO")
    if (secondary is None) != (third is None):
        raise ValueError("Supply either one or three thresholds")
    values = [number(degrees, 0, 90)]
    if secondary is not None and third is not None:
        values.extend((number(secondary, 0, 90), number(third, 0, 90)))
    return config("RTKELEVMASK", *values)


def antenna_power_on() -> Command[CommandResponse]:
    """Request antenna feed power, which board wiring may or may not deliver."""
    return config("ANTENNA", "POWERON")
