"""Typed commands for the baseband processor channel."""

from enum import StrEnum

from um982py.commands.core import Command
from um982py.commands.validation import integer
from um982py.experimental.debug import bb_command
from um982py.messages import CommandResponse


class SideEffect(StrEnum):
    """What executing a baseband command does to receiver state."""

    QUERY = "QUERY"
    """Inspect without changing receiver state."""

    CONFIGURATION = "CONFIGURATION"
    """Volatile setting or assistance update, possibly without a readback query."""

    DESTRUCTIVE = "DESTRUCTIVE"
    """Reset, forced state change, fault injection or persistent write."""

    UNVERIFIED = "UNVERIFIED"
    """Command whose full argument semantics or effects are not established."""

    NO_OP = "NO_OP"
    """Acknowledged without performing a configuration or query operation."""


class BasebandCommand(StrEnum):
    """The commands the baseband processor recognises."""

    RESET = "RESET"
    BBMSG2AP = "BBMSG2AP"
    LOG = "LOG"
    PPSCONFIG = "PPSCONFIG"
    TIMINGMODE = "TIMINGMODE"
    FRESET = "FRESET"
    EVENTCONFIG = "EVENTCONFIG"
    SBASCONTROL = "SBASCONTROL"
    FORCEERRORTRAP = "FORCEERRORTRAP"
    ACQFREQ = "ACQFREQ"
    TRACKMODE = "TRACKMODE"
    AEEN = "AEEN"
    RFSPIREAD = "RFSPIREAD"
    RFSPIWRITE = "RFSPIWRITE"
    SIGNALMASK = "SIGNALMASK"
    RFCONFIG = "RFCONFIG"
    PPPEN = "PPPEN"
    RECINFOEN = "RECINFOEN"
    RTCSTATUSEN = "RTCSTATUSEN"
    JAMSTATUSEN = "JAMSTATUSEN"
    SIGNALGROUP = "SIGNALGROUP"
    AIENA = "AIENA"
    AICONFIG = "AICONFIG"
    RCVRUNNINGMODE = "RCVRUNNINGMODE"
    MODE = "MODE"
    AGNSSINFO = "AGNSSINFO"
    AGNSSCONFIG = "AGNSSCONFIG"
    CFGWNKROR = "CFGWNKROR"
    ADRRELIABLITY = "ADRRELIABLITY"
    ADRINITIAL = "ADRINITIAL"
    MMPEN = "MMPEN"
    SATMASK = "SATMASK"
    HOTSTART = "HOTSTART"
    TCXOJUMPEN = "TCXOJUMPEN"
    DCRMSGEN = "DCRMSGEN"
    LEAPSECOND = "LEAPSECOND"
    CUSTOMMODE = "CUSTOMMODE"
    PPPRTKEN = "PPPRTKEN"
    ONESATTRK = "ONESATTRK"
    ANTISPOOFENA = "ANTISPOOFENA"
    BBLOGEN = "BBLOGEN"

    @property
    def category(self) -> SideEffect:
        """Return the side-effect class for this command."""
        return _SIDE_EFFECTS.get(self, SideEffect.UNVERIFIED)

    @property
    def notice(self) -> str | None:
        """Return the notice kind this command reports, or ``None`` if unknown."""
        return _NOTICES.get(self)


_NOTICES: dict[BasebandCommand, str] = {
    BasebandCommand.RESET: "RESET",
    BasebandCommand.PPSCONFIG: "PPSCONFIG",
    BasebandCommand.TIMINGMODE: "TIMINGMODE",
    BasebandCommand.FRESET: "FRESET",
    BasebandCommand.EVENTCONFIG: "EVENTCONFIG",
    BasebandCommand.SBASCONTROL: "SBASCONTROL",
    BasebandCommand.FORCEERRORTRAP: "FORCEERRORTRAP",
    BasebandCommand.ACQFREQ: "ACQFREQ",
    BasebandCommand.TRACKMODE: "TRACKMODE",
    BasebandCommand.RFSPIREAD: "RFSPIREAD",
    BasebandCommand.RFSPIWRITE: "RFSPIWRITE",
    BasebandCommand.RFCONFIG: "RFCONFIG",
    BasebandCommand.PPPEN: "PPPEN",
    BasebandCommand.RECINFOEN: "RECINFOEN",
    BasebandCommand.RTCSTATUSEN: "RTCSTATUSEN",
    BasebandCommand.JAMSTATUSEN: "JAMSTATUSEN",
    BasebandCommand.SIGNALGROUP: "SIGNALGROUP",
    BasebandCommand.AIENA: "AIENA",
    BasebandCommand.ADRRELIABLITY: "ADRRELIABLITY",
    BasebandCommand.ADRINITIAL: "ADRINITIAL",
    BasebandCommand.MMPEN: "MMPEN",
    BasebandCommand.PPPRTKEN: "PPPRTKEN",
    BasebandCommand.BBLOGEN: "BBLOGEN",
    BasebandCommand.LOG: "LOG_SWITCH",
    BasebandCommand.MODE: "RUNNING_MODE",
    BasebandCommand.RCVRUNNINGMODE: "RUNNING_MODE_MASK",
}


_DESTRUCTIVE = {
    BasebandCommand.RESET,
    BasebandCommand.FRESET,
    BasebandCommand.HOTSTART,
    BasebandCommand.FORCEERRORTRAP,
    BasebandCommand.ONESATTRK,
    BasebandCommand.CUSTOMMODE,
    BasebandCommand.RCVRUNNINGMODE,
    BasebandCommand.CFGWNKROR,
    BasebandCommand.AIENA,
    BasebandCommand.SIGNALGROUP,
    BasebandCommand.RFSPIWRITE,
    BasebandCommand.RFCONFIG,
}
_QUERY = {
    BasebandCommand.RFSPIREAD,
}
_CONFIGURATION = {
    BasebandCommand.BBMSG2AP,
    BasebandCommand.LOG,
    BasebandCommand.PPSCONFIG,
    BasebandCommand.TIMINGMODE,
    BasebandCommand.EVENTCONFIG,
    BasebandCommand.SBASCONTROL,
    BasebandCommand.ACQFREQ,
    BasebandCommand.TRACKMODE,
    BasebandCommand.RFSPIWRITE,
    BasebandCommand.SIGNALMASK,
    BasebandCommand.RFCONFIG,
    BasebandCommand.PPPEN,
    BasebandCommand.RECINFOEN,
    BasebandCommand.RTCSTATUSEN,
    BasebandCommand.JAMSTATUSEN,
    BasebandCommand.SIGNALGROUP,
    BasebandCommand.AIENA,
    BasebandCommand.ADRRELIABLITY,
    BasebandCommand.ADRINITIAL,
    BasebandCommand.MMPEN,
    BasebandCommand.PPPRTKEN,
    BasebandCommand.ANTISPOOFENA,
    BasebandCommand.BBLOGEN,
    BasebandCommand.AEEN,
    BasebandCommand.AGNSSCONFIG,
    BasebandCommand.TCXOJUMPEN,
    BasebandCommand.DCRMSGEN,
    BasebandCommand.LEAPSECOND,
    BasebandCommand.AGNSSINFO,
}
_SIDE_EFFECTS: dict[BasebandCommand, SideEffect] = {
    **dict.fromkeys(_DESTRUCTIVE, SideEffect.DESTRUCTIVE),
    **dict.fromkeys(_QUERY, SideEffect.QUERY),
    **dict.fromkeys(_CONFIGURATION - _DESTRUCTIVE, SideEffect.CONFIGURATION),
    BasebandCommand.AICONFIG: SideEffect.NO_OP,
    BasebandCommand.SIGNALMASK: SideEffect.NO_OP,
    BasebandCommand.BBLOGEN: SideEffect.UNVERIFIED,
}


def baseband_message(command: BasebandCommand | str, *args: str) -> str:
    """Return the ``$NAME,...`` text the baseband parser receives."""
    name = command.value if isinstance(command, BasebandCommand) else command
    name = name.upper()
    if not name or any(not (32 <= ord(char) < 127) for char in name):
        raise ValueError("Baseband command name must be printable ASCII")
    if any(char.isspace() for char in name):
        raise ValueError("Baseband command name must not contain whitespace")
    tokens = [name, *args]
    for token in tokens:
        if not token or any(not (32 <= ord(char) < 127) for char in token):
            raise ValueError("Baseband command tokens must be printable ASCII")
        if any(char.isspace() for char in token):
            raise ValueError("Baseband command tokens must not contain whitespace")
        if any(char in token for char in "*#;,"):
            raise ValueError("Baseband command token contains a delimiter")
    return ",".join(tokens)


def baseband_command(
    command: BasebandCommand | str, *args: str
) -> Command[CommandResponse]:
    """Wrap a baseband message in ``BBCMD`` for application transport."""
    return bb_command("$" + baseband_message(command, *args))


def timing_mode(value: int) -> Command[CommandResponse]:
    """Select timing mode 0 or 1."""
    return baseband_command(BasebandCommand.TIMINGMODE, integer(value, 0, 1))


def track_mode(value: int) -> Command[CommandResponse]:
    """Select tracking mode 0 or 1."""
    return baseband_command(BasebandCommand.TRACKMODE, integer(value, 0, 1))


def acquisition_frequency_mask(mask: int) -> Command[CommandResponse]:
    """Set the acquisition mask using the parser's signed decimal representation."""
    integer(mask, 0, 0xFFFFFFFF)
    value = mask if mask < 1 << 31 else mask - (1 << 32)
    return baseband_command(BasebandCommand.ACQFREQ, str(value))


def _integers(values: tuple[int, ...], count: int) -> tuple[str, ...]:
    if len(values) != count:
        raise ValueError(f"expected exactly {count} integers, got {len(values)}")
    return tuple(integer(v, 0, 0x7FFFFFFF) for v in values)


def signal_mask(*values: int) -> Command[CommandResponse]:
    """Build SIGNALMASK's two native arguments, whose operation is a no-op."""
    return baseband_command(BasebandCommand.SIGNALMASK, *_integers(values, 2))


def signal_group(*values: int) -> Command[CommandResponse]:
    """Build ``SIGNALGROUP <n>,<n>`` and expect ``$SignalGroupConfig,%d,%d``."""
    return baseband_command(BasebandCommand.SIGNALGROUP, *_integers(values, 2))


def event_config(*values: int) -> Command[CommandResponse]:
    """Build ``EVENTCONFIG <a>,<b>,<c>,<d>`` and parse its four-field reply."""
    return baseband_command(BasebandCommand.EVENTCONFIG, *_integers(values, 4))


def ai_enable(value: int) -> Command[CommandResponse]:
    """Build ``AIENA <n>`` and expect the reply ``$AIENA: %d``."""
    return baseband_command(BasebandCommand.AIENA, integer(value, 0, 0x7FFFFFFF))


def ppp_enable(value: int) -> Command[CommandResponse]:
    """Build ``PPPEN <n>`` and expect the reply ``LogPPPCMD: %d``."""
    return baseband_command(BasebandCommand.PPPEN, integer(value, 0, 0x7FFFFFFF))


def ppp_rtk_enable(value: int) -> Command[CommandResponse]:
    """Build ``PPPRTKEN <n>`` and expect the reply ``LogPPPRTKCMD: %d``."""
    return baseband_command(BasebandCommand.PPPRTKEN, integer(value, 0, 0x7FFFFFFF))


def rec_info_enable(value: int) -> Command[CommandResponse]:
    """Build ``RECINFOEN <n>`` and expect the reply ``LogRECINFOENCMD: %d``."""
    return baseband_command(BasebandCommand.RECINFOEN, integer(value, 0, 0x7FFFFFFF))


def rtc_status_enable(value: int) -> Command[CommandResponse]:
    """Build ``RTCSTATUSEN <n>`` and expect the reply ``SendRTCInfoEn, %d``."""
    return baseband_command(BasebandCommand.RTCSTATUSEN, integer(value, 0, 0x7FFFFFFF))


def jam_status_enable(value: int) -> Command[CommandResponse]:
    """Build ``JAMSTATUSEN <n>`` and expect the reply ``SendJAMInfoEn, %d``."""
    return baseband_command(BasebandCommand.JAMSTATUSEN, integer(value, 0, 0x7FFFFFFF))


def adr_reliability(value: int) -> Command[CommandResponse]:
    """Select carrier-phase reliability level 1..4."""
    return baseband_command(BasebandCommand.ADRRELIABLITY, integer(value, 1, 4))


def adr_initial(value: int) -> Command[CommandResponse]:
    """Build ``ADRINITIAL <n>`` and expect the reply ``$Parse ADRInitial: %d``."""
    return baseband_command(BasebandCommand.ADRINITIAL, integer(value, 0, 0x7FFFFFFF))


def mmp_enable(value: int) -> Command[CommandResponse]:
    """Build ``MMPEN <n>`` and expect the reply ``$Parse MMP Ena: %d``."""
    return baseband_command(BasebandCommand.MMPEN, integer(value, 0, 0x7FFFFFFF))


def sbas_control(*values: int) -> Command[CommandResponse]:
    """Build ``SBASCONTROL <a>,<b>,<c>,<d>`` and expect ``#DoSBASCONTROL``."""
    return baseband_command(BasebandCommand.SBASCONTROL, *_integers(values, 4))


def log_enable(value: int) -> Command[CommandResponse]:
    """Set the first native word of a LOG command, which is not a message ID."""
    return baseband_command(BasebandCommand.LOG, integer(value, 0, 0x7FFFFFFF))


def log_config(interval: int, *, mode: int = 0) -> Command[CommandResponse]:
    """Set the native LOG interval and mode 0..2, whose units are unspecified."""
    return baseband_command(
        BasebandCommand.LOG, integer(interval, 0, 0xFFFF), integer(mode, 0, 2)
    )


def bb_message_to_ap(*, enabled: bool = True) -> Command[CommandResponse]:
    """Build ``BBMSG2AP``, the baseband-to-application forwarding gate."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return baseband_command(BasebandCommand.BBMSG2AP, "1" if enabled else "0")


def rf_spi_read(address: int) -> Command[CommandResponse]:
    """Read selector 0..124, or use 0xFFFFFFFF to read all RF registers."""
    integer(address, 0, 0xFFFFFFFF)
    if address > 124 and address != 0xFFFFFFFF:
        raise ValueError("RF SPI selector must be in 0..124 or 0xFFFFFFFF")
    return baseband_command(BasebandCommand.RFSPIREAD, f"{address:010X}")


def rf_spi_write(address: int) -> Command[CommandResponse]:
    """Write a packed selector and value, where 0xFF selects bulk RF config."""
    integer(address, 0, (1 << 40) - 1)
    if address >> 32 > 124 and address >> 32 != 0xFF:
        raise ValueError("Packed RF SPI selector must be in 0..124 or 0xFF")
    return baseband_command(BasebandCommand.RFSPIWRITE, f"{address:010X}")


def rf_spi_register_write(register: int, value: int) -> Command[CommandResponse]:
    """Write a 32-bit RF register value through selector 0..124."""
    integer(register, 0, 124)
    integer(value, 0, 0xFFFFFFFF)
    return rf_spi_write((register << 32) | value)


def ae_enable(value: int) -> Command[CommandResponse]:
    """Set the native 16-bit AE control value without truncation."""
    return baseband_command(BasebandCommand.AEEN, integer(value, 0, 0xFFFF))


def agnss_config(*, enabled: bool) -> Command[CommandResponse]:
    """Enable or clear the baseband AGNSS configuration bit."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return baseband_command(BasebandCommand.AGNSSCONFIG, "1" if enabled else "0")


def tcxo_jump_config(value: int, *, parameter: int) -> Command[CommandResponse]:
    """Set the two signed TCXO jump control words, whose units are unspecified."""
    return baseband_command(
        BasebandCommand.TCXOJUMPEN,
        integer(value, -(1 << 31), (1 << 31) - 1),
        integer(parameter, -(1 << 31), (1 << 31) - 1),
    )


def dc_message_enable(value: int) -> Command[CommandResponse]:
    """Set the native signed DCRMSGEN control word."""
    return baseband_command(
        BasebandCommand.DCRMSGEN, integer(value, -(1 << 31), (1 << 31) - 1)
    )


def leap_second_config(seconds: int, *, enabled: bool) -> Command[CommandResponse]:
    """Configure the baseband leap-second override and its signed seconds value."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return baseband_command(
        BasebandCommand.LEAPSECOND,
        "1" if enabled else "0",
        integer(seconds, -(1 << 31), (1 << 31) - 1),
    )


def agnss_info(*values: int) -> Command[CommandResponse]:
    """Supply six native assistance words as a command, which is not a query."""
    if len(values) != 6:
        raise ValueError("AGNSSINFO requires six native assistance words")
    limits = [(0, 0xFFFF), (-(1 << 31), (1 << 31) - 1), (-128, 127)] + [
        (-(1 << 31), (1 << 31) - 1)
    ] * 3
    arguments = tuple(
        integer(value, minimum, maximum)
        for value, (minimum, maximum) in zip(values, limits, strict=True)
    )
    return baseband_command(BasebandCommand.AGNSSINFO, *arguments)


def dangerous_reset(flags: int = 0, *, mode: int = 0) -> Command[CommandResponse]:
    """Reset the baseband with a 32-bit flag word and a signed mode."""
    integer(flags, 0, 0xFFFFFFFF)
    return baseband_command(
        BasebandCommand.RESET,
        f"{flags:08X}",
        integer(mode, -(1 << 31), (1 << 31) - 1),
    )


def dangerous_force_reset(value: int = 0) -> Command[CommandResponse]:
    """Force a baseband reset with the required signed control word."""
    return baseband_command(
        BasebandCommand.FRESET, integer(value, -(1 << 31), (1 << 31) - 1)
    )


def dangerous_hot_start() -> Command[CommandResponse]:
    """Forces ``HOTSTART`` on the baseband, resetting the PVT state."""
    return baseband_command(BasebandCommand.HOTSTART)


def dangerous_force_error_trap(value: int) -> Command[CommandResponse]:
    """Inject a fatal error trap for a nonzero signed decimal control word."""
    return baseband_command(
        BasebandCommand.FORCEERRORTRAP, integer(value, -(1 << 31), (1 << 31) - 1)
    )


def dangerous_single_satellite_tracking(
    *, enabled: bool = True
) -> Command[CommandResponse]:
    """Enable or clear single-satellite tracking."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return baseband_command(BasebandCommand.ONESATTRK, "1" if enabled else "0")


UNVERIFIED_COMMANDS = (
    BasebandCommand.MODE,
    BasebandCommand.SATMASK,
    BasebandCommand.BBLOGEN,
)
"""Commands whose full argument semantics or effects are not established."""


__all__ = [
    "UNVERIFIED_COMMANDS",
    "BasebandCommand",
    "SideEffect",
    "acquisition_frequency_mask",
    "adr_initial",
    "adr_reliability",
    "ae_enable",
    "agnss_config",
    "agnss_info",
    "ai_enable",
    "baseband_command",
    "baseband_message",
    "bb_message_to_ap",
    "dangerous_force_error_trap",
    "dangerous_force_reset",
    "dangerous_hot_start",
    "dangerous_reset",
    "dangerous_single_satellite_tracking",
    "dc_message_enable",
    "event_config",
    "jam_status_enable",
    "leap_second_config",
    "log_config",
    "log_enable",
    "mmp_enable",
    "ppp_enable",
    "ppp_rtk_enable",
    "rec_info_enable",
    "rf_spi_read",
    "rf_spi_register_write",
    "rf_spi_write",
    "rtc_status_enable",
    "sbas_control",
    "signal_group",
    "signal_mask",
    "tcxo_jump_config",
    "timing_mode",
    "track_mode",
]
