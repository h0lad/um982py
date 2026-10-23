"""Positioning, RTK and smoothing CONFIG commands."""

from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, positive, switch
from um982py.messages import CommandResponse


def dgps_timeout(seconds: int) -> Command[CommandResponse]:
    return config("DGPS TIMEOUT", integer(seconds, 0, 1800))


def rtk_timeout(seconds: int) -> Command[CommandResponse]:
    return config("RTK TIMEOUT", integer(seconds, 0, 1800))


def rtk_reliability(
    position: int = 3, adr: int | None = None
) -> Command[CommandResponse]:
    values = [integer(position, 1, 4)]
    if adr is not None:
        values.append(integer(adr, 1, 4))
    return config("RTK RELIABILITY", *values)


def rtk_cn0_threshold(high: bool = False) -> Command[CommandResponse]:
    return config("RTK CN0THD", str(int(high)))


def rtk_multipath_threshold(high: bool = False) -> Command[CommandResponse]:
    return config("RTK MMPL", str(int(high)))


def rtk_defaults() -> Command[CommandResponse]:
    return config("RTK USER_DEFAULTS")


def rtk_reset() -> Command[CommandResponse]:
    return config("RTK RESET")


def rtk_disable() -> Command[CommandResponse]:
    return config("RTK DISABLE")


def standalone(
    *,
    enabled: bool = True,
    coordinates: tuple[float, float, float] | None = None,
    wait_seconds: int | None = None,
) -> Command[CommandResponse]:
    if coordinates is not None and wait_seconds is not None:
        raise ValueError("Choose coordinates or a waiting time")
    if not enabled:
        if coordinates is not None or wait_seconds is not None:
            raise ValueError("Disabled standalone mode takes no parameters")
        return config("STANDALONE DISABLE")
    if coordinates is not None:
        lat, lon, height = coordinates
        return config(
            "STANDALONE ENABLE",
            number(lat, -90, 90),
            number(lon, -180, 180),
            number(height, -30000, 18000),
        )
    if wait_seconds is not None:
        return config("STANDALONE ENABLE", integer(wait_seconds, 3, 100))
    return config("STANDALONE ENABLE")


def standalone_timeout(seconds: int) -> Command[CommandResponse]:
    """Set the standalone duration in seconds (R1.15 section 4.50)."""
    return config("STANDALONE TIMEOUT", integer(seconds, 1800, 86400))


def smooth_rtk_height(epochs: int) -> Command[CommandResponse]:
    return config("SMOOTH RTKHEIGHT", integer(epochs, 0, 100))


def smooth_heading(
    epochs: int, level_epochs: int | None = None, *, pitch_epochs: int | None = None
) -> Command[CommandResponse]:
    """Configure heading and optional pitch smoothing in epochs (0..100).

    ``level_epochs`` is the historical name for the second argument, which
    R1.15 describes as pitch, so use ``pitch_epochs`` in new code. Firmware
    support for the optional argument can vary.
    """
    if level_epochs is not None and pitch_epochs is not None:
        raise ValueError("Specify pitch_epochs or the legacy level_epochs, not both")
    parameters = [integer(epochs, 0, 100)]
    pitch = pitch_epochs if pitch_epochs is not None else level_epochs
    if pitch is not None:
        parameters.append(integer(pitch, 0, 100))
    return config("SMOOTH HEADING", *parameters)


def smooth_velocity(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("SMOOTH PSRVEL", enabled)


def pvt_algorithm(mode: Literal["SINGLE", "AUTO", "MULTI"]) -> Command[CommandResponse]:
    return config("PVTALG", option(mode, ("SINGLE", "AUTO", "MULTI")))


def position_bias(*, enabled: bool = True) -> Command[CommandResponse]:
    return switch("PSRPOSBIAS", enabled)


def velocity_std_threshold(
    *, enabled: bool = True, horizontal: int = 50, vertical: int = 50
) -> Command[CommandResponse]:
    """Set velocity STD thresholds in integer cm/s, from 10 to 1000."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    if not enabled:
        return config("VELSTDTHD DISABLE")
    return config(
        "VELSTDTHD ENABLE", integer(horizontal, 10, 1000), integer(vertical, 10, 1000)
    )


def algorithm_reset(
    engine: Literal["RTK1", "RTK2", "HEADING", "PPP", "ADR"],
) -> Command[CommandResponse]:
    return config("ALGRESET", option(engine, ("RTK1", "RTK2", "HEADING", "PPP", "ADR")))


def ppp_rtk(
    *,
    enabled: bool = True,
    service: Literal["L6CLAS"] | None = None,
    timeout: int | None = None,
    convergence: tuple[float, float] | None = None,
) -> Command[CommandResponse]:
    """Configure PPPRTK positioning (L6CLAS) for UM980C/UM982C.

    Requires SIGNALGROUP 3 6 on UM982C. Actions are exclusive: DISABLE,
    ENABLE [L6CLAS], TIMEOUT (0 disables, 90..600 s), or
    CONVERGE <horizontal_cm> <vertical_cm>.
    """
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    if sum(value is not None for value in (service, timeout, convergence)) > 1:
        raise ValueError("Choose only one PPPRTK action")
    if not enabled:
        if any(v is not None for v in (service, timeout, convergence)):
            raise ValueError("Disabled PPPRTK takes no parameters")
        return config("PPPRTK DISABLE")
    if service is not None:
        return config("PPPRTK ENABLE", option(service, ("L6CLAS",)))
    if timeout is not None:
        if type(timeout) is int and timeout == 0:
            return config("PPPRTK TIMEOUT", "0")
        return config("PPPRTK TIMEOUT", integer(timeout, 90, 600))
    if convergence is not None:
        horizontal_cm, vertical_cm = convergence
        return config("PPPRTK CONVERGE", positive(horizontal_cm), positive(vertical_cm))
    return config("PPPRTK ENABLE")


def pvt_reliability(first: int, second: int, third: int) -> Command[CommandResponse]:
    """Set horizontal, vertical, and Doppler reliability levels, each 1 to 3."""
    return config(
        "PVT RELIABILITY", *(integer(value, 1, 3) for value in (first, second, third))
    )
