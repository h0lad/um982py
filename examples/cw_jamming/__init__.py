"""Classifies continuous-wave jamming from JAMSTATUS and FREQJAMSTATUS."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from um982py.messages import Record, Value

CW_RATIO_MAXIMUM = 255

__all__ = [
    "CW_FLAGS",
    "CW_RATIO_MAXIMUM",
    "SEVERITY_ORDER",
    "Band",
    "BandFingerprint",
    "CwFlag",
    "CwState",
    "Evidence",
    "InterferenceClass",
    "JamAlert",
    "JamSample",
    "JamTimeline",
    "alerts",
    "band_samples",
    "fingerprint",
    "flag_of",
    "freq_jam_states",
    "jam_state",
    "severity_rank",
    "timeline",
    "worst_flag",
]


class Band(StrEnum):
    """Frequency band reported by FREQJAMSTATUS."""

    L1 = "L1"
    L2 = "L2"
    L5 = "L5"


class CwFlag(StrEnum):
    """Continuous-wave jamming class as the interface guide defines it."""

    NO_JAM = "no_cw_jam"
    JAM = "cw_jam"
    STRONG_JAM = "strong_cw_jam"


CW_FLAGS: Mapping[int, CwFlag] = MappingProxyType(
    {0: CwFlag.NO_JAM, 1: CwFlag.JAM, 2: CwFlag.STRONG_JAM}
)

SEVERITY_ORDER: tuple[CwFlag, ...] = (CwFlag.NO_JAM, CwFlag.JAM, CwFlag.STRONG_JAM)


@dataclass(frozen=True, slots=True)
class CwState:
    """Continuous-wave jamming strength and class of one detector."""

    ratio: int
    flag: CwFlag

    @property
    def is_jammed(self) -> bool:
        """True when the class reports CW jamming of either severity."""
        return self.flag is not CwFlag.NO_JAM


@dataclass(frozen=True, slots=True)
class JamSample:
    """One band state at one capture epoch."""

    epoch: int
    band: Band
    state: CwState


@dataclass(frozen=True, slots=True)
class JamTimeline:
    """Aggregated continuous-wave jamming history of one detector series."""

    epochs: int
    jammed_epochs: int
    worst_flag: CwFlag
    peak_ratio: int
    first_jam_epoch: int | None


@dataclass(frozen=True, slots=True)
class JamAlert:
    """A change of the reported jamming class on one band."""

    epoch: int
    band: Band
    previous: CwFlag
    current: CwFlag
    ratio: int


def flag_of(code: int) -> CwFlag:
    """Jamming class of a documented 0/1/2 code."""
    try:
        return CW_FLAGS[code]
    except KeyError:
        raise ValueError(f"unknown jamming flag {code}") from None


def severity_rank(flag: CwFlag) -> int:
    """Position of a jamming class in the interface guide's 0/1/2 order."""
    return SEVERITY_ORDER.index(flag)


def worst_flag(flags: Sequence[CwFlag]) -> CwFlag:
    """Most severe class among the given flags."""
    if not flags:
        raise ValueError("at least one flag is required")
    return max(flags, key=severity_rank)


def state_of(ratio: Value, flag: Value) -> CwState:
    """Validate one decoded strength and flag pair."""
    if not isinstance(ratio, int):
        raise ValueError("jamming ratio is not an integer")
    if not isinstance(flag, int):
        raise ValueError("jamming flag is not an integer")
    if not 0 <= ratio <= CW_RATIO_MAXIMUM:
        raise ValueError(f"jamming ratio {ratio} is outside 0..{CW_RATIO_MAXIMUM}")
    return CwState(ratio=ratio, flag=flag_of(flag))


def jam_state(record: Record) -> CwState:
    """Continuous-wave jamming state of a decoded JAMSTATUS record."""
    return state_of(record["cwratio"], record["cwflag"])


def freq_jam_states(record: Record) -> tuple[tuple[Band, CwState], ...]:
    """Per-band continuous-wave jamming state of a decoded FREQJAMSTATUS record."""
    return (
        (Band.L1, state_of(record["l1cwratio"], record["l1cwflag"])),
        (Band.L2, state_of(record["l2cwratio"], record["l2cwflag"])),
        (Band.L5, state_of(record["l5cwratio"], record["l5cwflag"])),
    )


def band_samples(records: Sequence[Record]) -> tuple[JamSample, ...]:
    """One sample per band per FREQJAMSTATUS record, in capture order."""
    return tuple(
        JamSample(epoch=epoch, band=band, state=state)
        for epoch, record in enumerate(records)
        for band, state in freq_jam_states(record)
    )


def timeline(states: Sequence[CwState]) -> JamTimeline:
    """Aggregate one detector series into counts, worst class and peak strength."""
    if not states:
        raise ValueError("at least one sample is required")
    jammed = [state for state in states if state.is_jammed]
    first = next((index for index, state in enumerate(states) if state.is_jammed), None)
    return JamTimeline(
        epochs=len(states),
        jammed_epochs=len(jammed),
        worst_flag=worst_flag([state.flag for state in states]),
        peak_ratio=max(state.ratio for state in states),
        first_jam_epoch=first,
    )


def alerts(samples: Sequence[JamSample]) -> tuple[JamAlert, ...]:
    """Every change of jamming class, per band, ordered by epoch then band."""
    previous: dict[Band, CwFlag] = {}
    found: list[JamAlert] = []
    for sample in samples:
        before = previous.get(sample.band, CwFlag.NO_JAM)
        previous[sample.band] = sample.state.flag
        if sample.state.flag is before:
            continue
        found.append(
            JamAlert(
                epoch=sample.epoch,
                band=sample.band,
                previous=before,
                current=sample.state.flag,
                ratio=sample.state.ratio,
            )
        )
    return tuple(sorted(found, key=lambda alert: (alert.epoch, str(alert.band))))


class InterferenceClass(StrEnum):
    """Band occupancy of one epoch, which separates CW from wideband sources."""

    QUIET = "quiet"
    NARROWBAND = "narrowband_cw"
    WIDEBAND = "wideband"


class Evidence(StrEnum):
    """Agreement between a detector's strength and its own class word."""

    CONSISTENT = "consistent"
    FLAG_WITHOUT_RATIO = "flag_without_ratio"
    RATIO_WITHOUT_FLAG = "ratio_without_flag"


@dataclass(frozen=True, slots=True)
class BandFingerprint:
    """Per-band jamming source class of one epoch and its internal evidence."""

    epoch: int
    interference: InterferenceClass
    evidence: Evidence
    jammed_bands: tuple[Band, ...]
    strongest: Band | None


def fingerprint(epoch: int, states: Mapping[Band, CwState]) -> BandFingerprint:
    """Classify an epoch as narrowband or wideband from the bands it reports.

    The receiver reports one class word and one strength per band, so the
    occupancy pattern separates a single-band source from a source that covers
    L1, L2 and L5 at once.  Contradictions between the class word and the
    strength are reported as evidence faults instead of being averaged away.
    """
    if not states:
        raise ValueError("at least one band state is required")
    if any(not 0 <= state.ratio <= CW_RATIO_MAXIMUM for state in states.values()):
        raise ValueError("band strength must be a documented ratio")
    jammed = tuple(
        band
        for band in (Band.L1, Band.L2, Band.L5)
        if band in states and states[band].is_jammed
    )
    if not jammed:
        interference = InterferenceClass.QUIET
    elif len(jammed) == len(Band):
        interference = InterferenceClass.WIDEBAND
    else:
        interference = InterferenceClass.NARROWBAND
    evidence = Evidence.CONSISTENT
    if any(states[band].is_jammed and states[band].ratio == 0 for band in states):
        evidence = Evidence.FLAG_WITHOUT_RATIO
    elif any(
        not states[band].is_jammed and states[band].ratio == CW_RATIO_MAXIMUM
        for band in states
    ):
        evidence = Evidence.RATIO_WITHOUT_FLAG
    strongest = (
        max(jammed, key=lambda band: (states[band].ratio, -list(Band).index(band)))
        if jammed
        else None
    )
    return BandFingerprint(epoch, interference, evidence, jammed, strongest)
