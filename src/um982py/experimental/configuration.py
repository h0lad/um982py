import re
from enum import StrEnum
from math import isfinite
from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, switch
from um982py.messages import CommandResponse, Message, Record, Sentence


def _mask_report(name: Literal["MASKBASE", "MASKOBS"]) -> Command[Record]:
    def matches(message: Message) -> bool:
        return (
            isinstance(message, Sentence)
            and message.name == "CONFIG"
            and message.fields[:1] == (name,)
        )

    def decode(message: Message) -> Record:
        if not isinstance(message, Sentence) or not matches(message):
            raise ValueError(f"Expected a {name} report")
        fields = message.fields[1:]
        detail = ",".join(fields)
        if name == "MASKBASE":
            if detail == "MASKBASE NONE":
                return Record(name, (("prns", ()), ("fields", fields)), message)
            if match := re.fullmatch(r"([A-Z]+)MaskPrn:([0-9,]+)", detail):
                prns = tuple(int(prn) for prn in match[2].strip(",").split(",") if prn)
                return Record(
                    name,
                    (("system", match[1]), ("prns", prns), ("fields", fields)),
                    message,
                )
        elif detail.startswith("MASKOBS "):
            _, _, reported = detail.partition(" ")
            threshold, _, signal = reported.strip().partition(" ")
            try:
                value = float(threshold)
            except ValueError:
                return Record(
                    name, (("native_label", reported), ("fields", fields)), message
                )
            if isfinite(value):
                return Record(
                    name,
                    (
                        ("native_threshold", value),
                        ("native_label", signal or None),
                        ("fields", fields),
                    ),
                    message,
                )
        return Record(name, (("fields", fields),), message)

    return Command(name, matches, decode)


def base_mask_report() -> Command[Record]:
    """Query firmware BASE PRN masks. Use Receiver.collect for all rows."""
    return _mask_report("MASKBASE")


def observation_mask_report() -> Command[Record]:
    """Query native observation masks. Use Receiver.collect for all rows."""
    return _mask_report("MASKOBS")


class FirmwareSwitch(StrEnum):
    """Configure a boolean firmware switch with ``.configure(enabled=...)``."""

    BD3 = "BD3"
    DUALBEST = "DUALBEST"
    MCPUIDLE = "MCPUIDLE"
    RTK_B1CB2A = "RTK B1CB2A"
    BASERANGE_B1CB2A = "BASERANGE B1CB2A"
    SFRTK = "SFRTK"
    BASEBIASCORR = "BASEBIASCORR"
    BESTSATSYNC = "BESTSATSYNC"
    HEADING_DUALPOS = "HEADING DUALPOS"
    BBL1MASTER = "BBL1MASTER"
    RTCML1MASTER = "RTCML1MASTER"
    VELDRPOS2 = "VELDRPOS2"
    MVCHECK = "MVCHECK"

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
    """Select TRACKMODE 0 or 1. The meaning of each mode remains unverified."""
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
    """Select AUTO or set one or three elevation thresholds from 0 to 90 degrees."""
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
    """Request antenna feed power. Delivery depends on the board wiring."""
    return config("ANTENNA", "POWERON")


def remote_antenna_phase_center_offset(
    north_mm: float, east_mm: float, up_mm: float
) -> Command[CommandResponse]:
    """Set the remote base antenna's ARP-to-phase-center offset in millimetres."""
    return config(
        "REMOTEANTENNAPCO",
        *(number(value, -1_000_000, 1_000_000) for value in (north_mm, east_mm, up_mm)),
    )
