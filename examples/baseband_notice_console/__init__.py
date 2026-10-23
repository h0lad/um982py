"""Rebuilds one baseband state by replaying the notice lines."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from itertools import pairwise

from um982py.experimental import (
    BasebandNotice,
    BasebandSolution,
    decode_baseband_notice,
    solution_jump_m,
)
from um982py.messages.record import Record

LOG_ENABLE_COUNT = 27
EVENT_CONFIG_COUNT = 4

__all__ = [
    "EVENT_CONFIG_COUNT",
    "LOG_ENABLE_COUNT",
    "BasebandState",
    "apply_notices",
    "solution_summary",
    "state_sequence",
]


@dataclass(frozen=True, slots=True)
class BasebandState:
    """Baseband configuration reconstructed from the notice stream."""

    timing_mode: int | None = None
    track_mode: int | None = None
    acquisition_mask: int | None = None
    signal_group: tuple[int, ...] | None = None
    event_config: tuple[int, ...] | None = None
    ai_enable: int | None = None
    ppp_enable: int | None = None
    ppp_rtk_enable: int | None = None
    record_info_enable: int | None = None
    rtc_status_enable: int | None = None
    jam_status_enable: int | None = None
    adr_reliability: int | None = None
    adr_initial: int | None = None
    mmp_enable: int | None = None
    log_enable: tuple[int, ...] | None = None

    def applied(self, notice: BasebandNotice) -> BasebandState:
        """Return the state after one notice, leaving it unchanged for events."""
        record = decode_baseband_notice(notice)
        match notice.name:
            case "TIMINGMODE":
                return replace(self, timing_mode=record.integer("value"))
            case "TRACKMODE":
                return replace(self, track_mode=record.integer("value"))
            case "ACQFREQ":
                return replace(self, acquisition_mask=record.integer("mask"))
            case "SIGNALGROUP":
                return replace(self, signal_group=_values(record, "value", 2))
            case "EVENTCONFIG":
                return replace(
                    self, event_config=_values(record, "value", EVENT_CONFIG_COUNT)
                )
            case "AIENA":
                return replace(self, ai_enable=record.integer("value"))
            case "PPPEN":
                return replace(self, ppp_enable=record.integer("value"))
            case "PPPRTKEN":
                return replace(self, ppp_rtk_enable=record.integer("value"))
            case "RECINFOEN":
                return replace(self, record_info_enable=record.integer("value"))
            case "RTCSTATUSEN":
                return replace(self, rtc_status_enable=record.integer("value"))
            case "JAMSTATUSEN":
                return replace(self, jam_status_enable=record.integer("value"))
            case "ADRRELIABLITY":
                return replace(self, adr_reliability=record.integer("value"))
            case "ADRINITIAL":
                return replace(self, adr_initial=record.integer("value"))
            case "MMPEN":
                return replace(self, mmp_enable=record.integer("value"))
            case "BBLOGEN":
                return replace(
                    self, log_enable=_values(record, "value", LOG_ENABLE_COUNT)
                )
            case _:
                return self


def _values(record: Record, prefix: str, count: int) -> tuple[int, ...]:
    return tuple(record.integer(f"{prefix}_{index}") for index in range(1, count + 1))


def state_sequence(
    notices: Iterable[BasebandNotice], initial: BasebandState | None = None
) -> tuple[BasebandState, ...]:
    """Cumulative state after each notice, in stream order."""
    state = BasebandState() if initial is None else initial
    applied = []
    for notice in notices:
        state = state.applied(notice)
        applied.append(state)
    return tuple(applied)


def apply_notices(
    notices: Iterable[BasebandNotice], initial: BasebandState | None = None
) -> BasebandState:
    """Final state after replaying every notice of a stream."""
    state = BasebandState() if initial is None else initial
    for notice in notices:
        state = state.applied(notice)
    return state


def solution_summary(notices: Iterable[BasebandNotice]) -> dict[str, float]:
    """Agreement of the baseband position lines of a stream, in metres."""
    solutions = [
        BasebandSolution.from_record(notice.decode())
        for notice in notices
        if notice.name == "NAVPOS"
    ]
    jumps = [
        solution_jump_m(previous, current) for previous, current in pairwise(solutions)
    ]
    return {
        "count": float(len(solutions)),
        "worst_residual_m": max(
            (solution.ecef_residual_m for solution in solutions), default=0.0
        ),
        "worst_jump_m": max(jumps, default=0.0),
    }
