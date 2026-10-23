"""Heading and dual-antenna CONFIG commands."""

from typing import Literal

from um982py.commands.core import Command, number
from um982py.commands.validation import config, integer, option, positive
from um982py.messages import CommandResponse

HeadingMode = Literal["FIXLENGTH", "VARIABLELENGTH", "STATIC", "LOWDYNAMIC", "TRACTOR"]


def heading_mode(mode: HeadingMode) -> Command[CommandResponse]:
    return config(
        "HEADING",
        option(
            mode, ("FIXLENGTH", "VARIABLELENGTH", "STATIC", "LOWDYNAMIC", "TRACTOR")
        ),
    )


def heading_length(
    length_cm: float | None = None, tolerance_cm: float | None = None
) -> Command[CommandResponse]:
    if length_cm is None and tolerance_cm is None:
        return config("HEADING LENGTH")
    if length_cm is None or tolerance_cm is None:
        raise ValueError("Both baseline length and tolerance are required")
    if tolerance_cm <= 0:
        raise ValueError("Baseline tolerance must be greater than zero")
    return config("HEADING LENGTH", positive(length_cm), positive(tolerance_cm))


def heading_reliability(threshold: int = 3) -> Command[CommandResponse]:
    return config("HEADING RELIABILITY", integer(threshold, 1, 4))


def heading_offset(heading: float, pitch: float) -> Command[CommandResponse]:
    return config("HEADING OFFSET", number(heading, -180, 180), number(pitch, -90, 90))
