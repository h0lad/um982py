"""Correction, PPP and ionosphere CONFIG commands."""

from decimal import Decimal
from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, positive, switch
from um982py.messages import CommandResponse


def sbas(*, enabled: bool = True, service: str = "AUTO") -> Command[CommandResponse]:
    if not enabled:
        return config("SBAS DISABLE")
    return config(
        "SBAS ENABLE",
        option(
            service,
            (
                "AUTO",
                "QZSS",
                "WAAS",
                "GAGAN",
                "MSAS",
                "EGNOS",
                "SDCM",
                "ASECNA",
                "KASS",
                "SPAN",
                "BDS",
            ),
        ),
    )


def sbas_timeout(seconds: int) -> Command[CommandResponse]:
    integer(seconds, 0, 1800)
    if seconds == 0:
        return config("SBAS TIMEOUT", "0")
    return config("SBAS TIMEOUT", integer(seconds, 120, 1800))


def mmp(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("MMP", enabled)


def rtcm_b1c_b2a(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("RTCMB1CB2A", enabled)


def rtcm_phase_rate(
    polarity: Literal["POSITIVE", "NEGATIVE"] = "POSITIVE",
) -> Command[CommandResponse]:
    return config("RTCMPHASERATE", option(polarity, ("POSITIVE", "NEGATIVE")))


def rtcm_clock_offset(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("RTCMCLOCKOFFSET", enabled)


def doppler_prediction(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("PSRVELDRPOS", enabled)


def agnss(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("AGNSS", enabled)


def ppp(
    *,
    enabled: bool = True,
    service: Literal["B2B-PPP", "E6-HAS", "AUTO", "SSR-RX", "L6MDCPPP"] = "B2B-PPP",
    only: bool = False,
) -> Command[CommandResponse]:
    """Configure a PPP service, using ONLY with a specific satellite service."""
    if not enabled:
        if only:
            raise ValueError("ONLY requires an enabled PPP service")
        return config("PPP DISABLE")
    selected = option(service, ("B2B-PPP", "E6-HAS", "AUTO", "SSR-RX", "L6MDCPPP"))
    if only and selected not in ("B2B-PPP", "E6-HAS", "L6MDCPPP"):
        raise ValueError("ONLY requires B2B-PPP, E6-HAS, or L6MDCPPP")
    return config("PPP ENABLE", selected, *(["ONLY"] if only else []))


def ppp_datum(
    datum: Literal["WGS84", "PPPORIGINAL"] = "PPPORIGINAL",
) -> Command[CommandResponse]:
    return config("PPP DATUM", option(datum, ("WGS84", "PPPORIGINAL")))


def ppp_timeout(seconds: int) -> Command[CommandResponse]:
    integer(seconds, 0, 180)
    if seconds == 0:
        return config("PPP TIMEOUT", "0")
    return config("PPP TIMEOUT", integer(seconds, 90, 180))


def ppp_convergence(
    horizontal_cm: float, vertical_cm: float
) -> Command[CommandResponse]:
    return config("PPP CONVERGE", positive(horizontal_cm), positive(vertical_cm))


def anti_jam(
    mode: Literal["DISABLE", "AUTO", "FORCE"] = "AUTO",
) -> Command[CommandResponse]:
    return config("ANTIJAM", option(mode, ("DISABLE", "AUTO", "FORCE")))


def ionosphere_model(
    model: Literal["GPSK8", "BD2K8"] = "GPSK8",
) -> Command[CommandResponse]:
    return config("IONMODE", option(model, ("GPSK8", "BD2K8")))


def rtcm_clock_drift(*, enabled: bool = True) -> Command[CommandResponse]:
    """Configure RTCM clock drift compensation.

    Applicable products: UM982, UM981, UMD981, UM981S, UMD981S.
    """
    return switch("RTCMCLOCKDRIFT", enabled)


def rtcm_decode_auto(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("RTCMDECAUTO", enabled)


def all_ephemerides(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("ALLEPHRTCM", enabled)


def rtk_assists_ppp(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("RTKASITPPP", enabled)


def anti_spoof(
    *, enabled: bool = True, level: int | None = None
) -> Command[CommandResponse]:
    """Configure ANTISPOOF with an optional level 1..4, level 1 by default."""
    command = switch("ANTISPOOF", enabled)
    if level is None:
        return command
    if not enabled:
        raise ValueError("Disabled ANTISPOOF takes no level")
    return config("ANTISPOOF ENABLE", integer(level, 1, 4))


def rtcm_output_mode(mode: Literal["AUTO", "BASE"]) -> Command[CommandResponse]:
    """Select the receiver's RTCMOUTPUT mode (AUTO or BASE)."""
    return config("RTCMOUTPUT", option(mode, ("AUTO", "BASE")))


def l_band(
    *,
    enabled: bool = True,
    beam_id: int | None = None,
    reliability: int | None = None,
    datum: Literal["WGS84", "LBANDORIGINAL"] | None = None,
    timeout: int | None = None,
) -> Command[CommandResponse]:
    """Configure L-band satellite reception for UM982C/UMD982C.

    Actions are exclusive: DISABLE, ENABLE AUTO, ENABLE BEAMID <ID 1..7>,
    RELIABILITY <1..3>, DATUM, or TIMEOUT (0 disables, 90..600 s).
    """
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    if sum(value is not None for value in (beam_id, reliability, datum, timeout)) > 1:
        raise ValueError("Choose only one L-band action")
    if not enabled:
        if any(v is not None for v in (beam_id, reliability, datum, timeout)):
            raise ValueError("Disabled LBAND takes no parameters")
        return config("LBAND DISABLE")
    if beam_id is not None:
        if type(beam_id) is not int or not 1 <= beam_id <= 7:
            raise ValueError("LBAND beam ID must be an integer 1..7")
        return config("LBAND ENABLE BEAMID", str(beam_id))
    if reliability is not None:
        return config("LBAND RELIABILITY", integer(reliability, 1, 3))
    if datum is not None:
        return config("LBAND DATUM", option(datum, ("WGS84", "LBANDORIGINAL")))
    if timeout is not None:
        if type(timeout) is int and timeout == 0:
            return config("LBAND TIMEOUT", "0")
        return config("LBAND TIMEOUT", integer(timeout, 90, 600))
    return config("LBAND ENABLE AUTO")


def tp_ion_use(*, enabled: bool = True) -> Command[CommandResponse]:
    """Enable or disable the TruePoint quality factor service.

    Availability depends on the receiver.
    """
    return switch("TPIONUSE", enabled)


def ionosphere_level(
    value: float | None = None, *, enabled: bool = True
) -> Command[CommandResponse]:
    """Set the ionosphere activity level, select AUTO, or disable it."""
    if not enabled:
        if value is not None:
            raise ValueError("disabled ionosphere level cannot specify a value")
        return config("IONLEVEL", "DISABLE")
    if value is None:
        return config("IONLEVEL", "AUTO")
    formatted = number(value, 0.5, 3)
    scaled = Decimal(formatted) * 10
    if scaled != scaled.to_integral_value():
        raise ValueError("Ionospheric level must have at most one decimal place")
    return config("IONLEVEL", formatted)
