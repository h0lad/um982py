"""PPS, event and timing CONFIG commands."""

from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option
from um982py.messages import CommandResponse


def pps(
    *,
    mode: Literal["DISABLE", "ENABLE", "ENABLE2", "ENABLE3"] = "ENABLE",
    reference: Literal["GPS", "BDS", "GAL", "GLO"] = "GPS",
    polarity: Literal["POSITIVE", "NEGATIVE"] = "POSITIVE",
    width_us: int = 500000,
    period_ms: int = 1000,
    rf_delay_ns: int = 0,
    user_delay_ns: int = 0,
) -> Command[CommandResponse]:
    selected = option(mode, ("DISABLE", "ENABLE", "ENABLE2", "ENABLE3"))
    if selected == "DISABLE":
        return config("PPS", selected)
    period = integer(period_ms, 50, 20000)
    width = integer(width_us, 1, period_ms * 1000 - 1)
    return config(
        "PPS",
        selected,
        option(reference, ("GPS", "BDS", "GAL", "GLO")),
        option(polarity, ("POSITIVE", "NEGATIVE")),
        width,
        period,
        integer(rf_delay_ns, -32768, 32767),
        integer(user_delay_ns, -100000000, 100000000),
    )


def event(
    *,
    enabled: bool = True,
    polarity: Literal["POSITIVE", "NEGATIVE"] = "POSITIVE",
    guard_ms: int = 4,
    secondary: bool = False,
) -> Command[CommandResponse]:
    name = "EVENT2" if secondary else "EVENT"
    if not enabled:
        return config(name, "DISABLE")
    return config(
        name,
        "ENABLE",
        option(polarity, ("POSITIVE", "NEGATIVE")),
        integer(guard_ms, 2, 3599999),
    )


def event2(
    *,
    enabled: bool = True,
    polarity: Literal["POSITIVE", "NEGATIVE"] = "POSITIVE",
    guard_ms: int = 4,
) -> Command[CommandResponse]:
    return event(enabled=enabled, polarity=polarity, guard_ms=guard_ms, secondary=True)


def undulation(separation: float | None = None) -> Command[CommandResponse]:
    return config(
        "UNDULATION", "AUTO" if separation is None else number(separation, -1000, 1000)
    )
