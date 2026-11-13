"""Application-selected checks for live GGA position updates."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic

from um982py.geodesy import haversine_distance
from um982py.live import PositionUpdate


@dataclass(frozen=True, slots=True)
class LiveLimits:
    max_gap_s: float | None = None
    max_correction_age_s: float | None = None
    max_displacement_rate_m_s: float | None = None
    min_satellites: int | None = None
    allowed_quality: frozenset[int] | None = None

    def __post_init__(self) -> None:
        for value in (
            self.max_gap_s,
            self.max_correction_age_s,
            self.max_displacement_rate_m_s,
        ):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError("limits must be finite and non-negative")
        if self.min_satellites is not None and self.min_satellites < 0:
            raise ValueError("min_satellites must be non-negative")
        if self.allowed_quality is not None and not self.allowed_quality:
            raise ValueError("allowed_quality must not be empty")


@dataclass(frozen=True, slots=True)
class LiveAssessment:
    update: PositionUpdate
    gap_s: float | None
    displacement_rate_m_s: float | None
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.reasons


@dataclass(frozen=True, slots=True)
class LiveStatus:
    """The latest assessment and its age, including an ongoing outage."""

    assessment: LiveAssessment | None
    age_s: float | None
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.reasons


class PositionMonitor:
    """Assess updates using host-monotonic frame-completion intervals.

    Displacement rate is the straight-line distance between fixes divided by
    their completion interval. Use one consumer per monitor.
    """

    def __init__(self, limits: LiveLimits) -> None:
        self.limits = limits
        self._previous: PositionUpdate | None = None
        self._latest: LiveAssessment | None = None

    def status(self, *, now: float | None = None) -> LiveStatus:
        """Assess freshness without waiting for another update.

        Times use the host monotonic clock. A correction age is advanced by
        the elapsed time since frame completion; receiver and transport latency
        are not included. Check connection health separately.
        """
        latest = self._latest
        if latest is None:
            return LiveStatus(None, None, ("position_unavailable",))
        current = monotonic() if now is None else now
        received = latest.update.received_monotonic
        if not isfinite(current) or current < received:
            raise ValueError("now must be a compatible monotonic time")
        age = current - received
        reasons = list(latest.reasons)
        if self.limits.max_gap_s is not None and age > self.limits.max_gap_s:
            reasons.append("position_stale")
        correction_limit = self.limits.max_correction_age_s
        correction_age = latest.update.fix.correction_age_s
        if (
            correction_limit is not None
            and correction_age is not None
            and isfinite(correction_age)
            and correction_age >= 0
            and correction_age + age > correction_limit
            and "correction_age_exceeded" not in reasons
        ):
            reasons.append("correction_age_exceeded")
        return LiveStatus(latest, age, tuple(reasons))

    def age(self, *, now: float | None = None) -> float | None:
        """Seconds since the latest update, or None before the first update."""
        if self._previous is None:
            return None
        value = monotonic() if now is None else now
        if not isfinite(value) or value < self._previous.received_monotonic:
            raise ValueError("now must be a compatible monotonic time")
        return value - self._previous.received_monotonic

    def observe(self, update: PositionUpdate) -> LiveAssessment:
        previous = self._previous
        if not isfinite(update.received_monotonic) or (
            previous is not None
            and update.received_monotonic < previous.received_monotonic
        ):
            raise ValueError("updates must have nondecreasing monotonic times")
        fix = update.fix
        reasons: list[str] = []
        if not fix.valid:
            reasons.append("solution_unavailable")
        if (
            self.limits.allowed_quality is not None
            and fix.quality not in self.limits.allowed_quality
        ):
            reasons.append("fix_quality_not_allowed")
        if self.limits.min_satellites is not None:
            if fix.satellites < 0:
                reasons.append("satellites_unknown")
            elif fix.satellites < self.limits.min_satellites:
                reasons.append("satellites_below_limit")
        if self.limits.max_correction_age_s is not None:
            age = fix.correction_age_s
            if age is None or not isfinite(age) or age < 0:
                reasons.append("correction_age_unknown")
            elif age > self.limits.max_correction_age_s:
                reasons.append("correction_age_exceeded")
        gap = (
            None
            if previous is None
            else update.received_monotonic - previous.received_monotonic
        )
        if (
            gap is not None
            and self.limits.max_gap_s is not None
            and gap > self.limits.max_gap_s
        ):
            reasons.append("gap_exceeded")
        rate: float | None = None
        if (
            previous is not None
            and gap is not None
            and gap > 0
            and previous.connection == update.connection
            and previous.fix.valid
            and fix.valid
        ):
            old = previous.fix
            if (
                old.latitude is not None
                and old.longitude is not None
                and fix.latitude is not None
                and fix.longitude is not None
            ):
                rate = (
                    haversine_distance(
                        old.latitude, old.longitude, fix.latitude, fix.longitude
                    )
                    / gap
                )
                if (
                    self.limits.max_displacement_rate_m_s is not None
                    and rate > self.limits.max_displacement_rate_m_s
                ):
                    reasons.append("displacement_rate_exceeded")
        if self.limits.max_displacement_rate_m_s is not None and rate is None:
            reasons.append("displacement_rate_unknown")
        assessment = LiveAssessment(update, gap, rate, tuple(reasons))
        self._previous = update
        self._latest = assessment
        return assessment
