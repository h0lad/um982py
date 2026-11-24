"""Watches jamming and spoofing through SPOOFINFO, ANTENNA and C/N0."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from um982py.capture import gps_signals
from um982py.messages import Record, SpoofInfo, Value
from um982py.stats import percentile

MAD_SCALE = 0.6745
COLLAPSE_THRESHOLD = 3.5
CRITICAL_THRESHOLD = 6.0
MINIMUM_SERIES = 5
REFERENCE_WINDOW = 60
MINIMUM_MAD_DB = 0.5


class AlertKind(StrEnum):
    """Source of a monitoring alert."""

    SPOOFING = "spoofing"
    ANTENNA = "antenna"
    CN0_COLLAPSE = "cn0_collapse"


class Severity(StrEnum):
    """Alert urgency."""

    WARNING = "warning"
    CRITICAL = "critical"


class AntennaState(StrEnum):
    """Antenna status labels emitted next to the numeric ANTENNA fields."""

    WORK = "WORK"
    RESERVED = "RSV"
    UNKNOWN = "UNKNOWN"


ANTENNA_STATES: Mapping[int, AntennaState] = MappingProxyType(
    {
        5: AntennaState.WORK,
        0: AntennaState.RESERVED,
    }
)


@dataclass(frozen=True, slots=True)
class Alert:
    """A monitoring alert with its capture epoch."""

    epoch: int
    kind: AlertKind
    severity: Severity
    satellites: tuple[int, ...] = ()
    """Satellites that triggered a C/N0 alert."""
    z_score: float | None = None
    """Worst robust z-score of a C/N0 alert."""


@dataclass(frozen=True, slots=True)
class Cn0Sample:
    """One C/N0 sample in dB-Hz for a satellite at a capture epoch."""

    epoch: int
    satellite: int
    cn0: float


@dataclass(frozen=True, slots=True)
class AntennaReport:
    """The three ANTENNA status words."""

    status_1: int
    status_2: int
    status_3: int

    @property
    def state_1(self) -> AntennaState:
        """Label of the first antenna status word."""
        return antenna_state(self.status_1)

    @property
    def state_2(self) -> AntennaState:
        """Label of the second antenna status word."""
        return antenna_state(self.status_2)

    @property
    def state_3(self) -> AntennaState:
        """Label of the third antenna status word."""
        return antenna_state(self.status_3)

    @property
    def is_degraded(self) -> bool:
        """True when either antenna is not reporting ``WORK``."""
        return (
            self.state_1 is not AntennaState.WORK
            or self.state_2 is not AntennaState.WORK
        )


def antenna_state(status: int) -> AntennaState:
    """Map an ANTENNA status integer to its captured label."""
    return ANTENNA_STATES.get(status, AntennaState.UNKNOWN)


def median(values: Sequence[float]) -> float:
    """Return the median of a sequence, or ``nan`` when it is empty."""
    return percentile(values, 0.5)


def median_absolute_deviation(values: Sequence[float]) -> float:
    """Median absolute deviation of a sequence from its own median."""
    return _deviation(values, median(values))


def _deviation(values: Sequence[float], middle: float) -> float:
    return median([abs(value - middle) for value in values])


def robust_z_score(value: float, reference: Sequence[float]) -> float:
    """Median/MAD z-score of ``value`` against a reference series."""
    if len(reference) < 2:
        raise ValueError("a reference series needs at least two values")
    middle = median(reference)
    deviation = _deviation(reference, middle)
    return _z_score(value, middle, deviation)


def _z_score(value: float, middle: float, deviation: float) -> float:
    if deviation == 0.0:
        return 0.0 if value == middle else math.copysign(math.inf, value - middle)
    return MAD_SCALE * (value - middle) / deviation


def cn0_samples(records: Sequence[Record]) -> tuple[Cn0Sample, ...]:
    """Strongest C/N0 per satellite for each RANGE record, in record order."""
    samples: list[Cn0Sample] = []
    for epoch, record in enumerate(records):
        strongest: dict[int, float] = {}
        for observation, _ in gps_signals(record, [1575.42e6], phase=False):
            satellite = observation.integer("prn")
            cn0 = observation.real("cn0")
            strongest[satellite] = max(cn0, strongest.get(satellite, cn0))
        samples.extend(
            Cn0Sample(epoch=epoch, satellite=satellite, cn0=cn0)
            for satellite, cn0 in sorted(strongest.items())
        )
    return tuple(samples)


def detect_cn0_collapse(
    samples: Sequence[Cn0Sample], *, threshold: float = COLLAPSE_THRESHOLD
) -> tuple[Alert, ...]:
    """Flag epochs where a satellite's C/N0 falls below ``-threshold`` sigma.

    Each sample is scored against the median and MAD of up to
    ``REFERENCE_WINDOW`` earlier samples of the same satellite, with the MAD
    floored at ``MINIMUM_MAD_DB`` so quantised plateaus do not give infinite
    scores. A satellite needs ``MINIMUM_SERIES`` earlier samples before it is
    tested.
    """
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    series: dict[int, list[Cn0Sample]] = {}
    for sample in samples:
        series.setdefault(sample.satellite, []).append(sample)
    collapsed: dict[int, tuple[list[int], float]] = {}
    for satellite, owned in series.items():
        for index, sample in enumerate(owned):
            # Causal reference: only earlier samples of this satellite count,
            # so the C/N0 rise after acquisition is never scored against the
            # settled level that follows it.
            reference = [
                earlier.cn0
                for earlier in owned[max(0, index - REFERENCE_WINDOW) : index]
            ]
            if len(reference) < MINIMUM_SERIES:
                continue
            middle = median(reference)
            deviation = max(_deviation(reference, middle), MINIMUM_MAD_DB)
            z_score = _z_score(sample.cn0, middle, deviation)
            if z_score > -threshold:
                continue
            satellites, worst = collapsed.get(sample.epoch, ([], math.inf))
            collapsed[sample.epoch] = ([*satellites, satellite], min(worst, z_score))
    return tuple(
        Alert(
            epoch=epoch,
            kind=AlertKind.CN0_COLLAPSE,
            severity=_severity(z_score),
            satellites=tuple(sorted(satellites)),
            z_score=z_score,
        )
        for epoch, (satellites, z_score) in sorted(collapsed.items())
    )


def antenna_report(record: Record) -> AntennaReport:
    """Decode the three ANTENNA status words."""
    return AntennaReport(
        status_1=_antenna_code(record["status_1"]),
        status_2=_antenna_code(record["status_2"]),
        status_3=_antenna_code(record["status_3"]),
    )


def _antenna_code(value: Value) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        for code, state in ANTENNA_STATES.items():
            if state == value:
                return code
        raise ValueError(f"unknown antenna status label {value}")
    raise ValueError("antenna status is neither a code nor a label")


def status_alerts(
    epoch: int,
    spoof: SpoofInfo | None,
    antenna: AntennaReport | None,
) -> tuple[Alert, ...]:
    """Alerts raised by the SPOOFINFO and ANTENNA status words."""
    alerts = []
    if spoof is not None and spoof.is_suspect:
        alerts.append(
            Alert(epoch=epoch, kind=AlertKind.SPOOFING, severity=Severity.CRITICAL)
        )
    if antenna is not None and antenna.is_degraded:
        alerts.append(
            Alert(epoch=epoch, kind=AlertKind.ANTENNA, severity=Severity.WARNING)
        )
    return tuple(alerts)


def _severity(z_score: float) -> Severity:
    """Severity of a collapse score."""
    return Severity.CRITICAL if z_score <= -CRITICAL_THRESHOLD else Severity.WARNING
