"""Sustained position quality over fresh, distinct receiver epochs."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING

from um982py.assessment import PositionAssessment, PositionLimits, assess_position

if TYPE_CHECKING:
    from um982py.messages.navigation import Position

__all__ = ["ConvergenceMonitor", "ConvergenceStatus"]


@dataclass(frozen=True, slots=True)
class ConvergenceStatus:
    """Current qualification of a position, not an accuracy or integrity guarantee."""

    assessment: PositionAssessment | None
    epochs: int
    span_s: float
    elapsed_s: float
    timed_out: bool
    reasons: tuple[str, ...]

    @property
    def converged(self) -> bool:
        return not self.timed_out and not self.reasons


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isfinite(value):
        raise ValueError(f"{name} must be finite")


class ConvergenceMonitor:
    """Require application quality limits over consecutive, fresh measurements.

    Supply at least one precision limit and ``max_epoch_age_s`` in ``limits``.
    Set ``max_correction_age_s`` for corrected solutions and
    ``allowed_fix_classes`` when a particular solution class is required.
    Each observation needs an independently verified current GPS time. Receiver
    timestamps must report fine time and a known GPS scale, because
    unverified binary time codes and date-less GGA cannot establish
    freshness.

    Both receiver time and host-monotonic time must span ``hold_seconds``.
    Duplicate epochs never advance the window or refresh its gap timer.
    Bad quality, backwards epochs and gaps reset the window. Call ``status()``
    from a timer to detect silence and ageing corrections without a new update.

    The attempt expires ``timeout`` seconds after construction, even if it
    previously qualified. Stop on success or create a new monitor for another
    attempt. Use one consumer, receiver, antenna and session per monitor.
    """

    def __init__(
        self,
        limits: PositionLimits,
        *,
        min_epochs: int = 5,
        hold_seconds: float = 30,
        max_gap_seconds: float = 5,
        timeout: float = 600,
    ) -> None:
        if not isinstance(limits, PositionLimits):
            raise TypeError("limits must be PositionLimits")
        if limits.max_epoch_age_s is None:
            raise ValueError("max_epoch_age_s is required to establish freshness")
        if limits.max_horizontal_rms_m is None and limits.max_vertical_std_m is None:
            raise ValueError("at least one position precision limit is required")
        if type(min_epochs) is not int or min_epochs < 2:
            raise ValueError("min_epochs must be an integer of at least 2")
        for name, value in (
            ("hold_seconds", hold_seconds),
            ("max_gap_seconds", max_gap_seconds),
            ("timeout", timeout),
        ):
            _finite(value, name)
        if hold_seconds < 0 or max_gap_seconds <= 0 or timeout <= 0:
            raise ValueError(
                "hold_seconds must be nonnegative, and gap and timeout positive"
            )
        if hold_seconds >= timeout:
            raise ValueError("hold_seconds must be less than timeout")
        self.limits = limits
        self.min_epochs = min_epochs
        self.hold_seconds = hold_seconds
        self.max_gap_seconds = max_gap_seconds
        self.timeout = timeout
        self._started = monotonic()
        self._now = self._started
        self._assessment: PositionAssessment | None = None
        self._observed_at = self._started
        self._last_epoch: float | None = None
        self._last_unique_at: float | None = None
        self._first_epoch: float | None = None
        self._first_at: float | None = None
        self._epochs = 0
        self._span = 0.0
        self._order_error = False

    def _time(self, now: float | None) -> float:
        current = monotonic() if now is None else now
        _finite(current, "now")
        if current < self._now:
            raise ValueError("now must be a nondecreasing compatible monotonic time")
        self._now = current
        return current

    def _reset_window(self) -> None:
        self._first_epoch = None
        self._first_at = None
        self._epochs = 0
        self._span = 0.0

    def _reasons(self, current: float) -> list[str]:
        assessment = self._assessment
        if assessment is None:
            return ["position_unavailable"]
        reasons = list(assessment.reasons)
        age = current - self._observed_at
        native = getattr(assessment.solution, "position", assessment.solution)
        for name, value, limit in (
            ("epoch_age", assessment.epoch_age_s, self.limits.max_epoch_age_s),
            (
                "correction_age",
                getattr(native, "correction_age_s", None),
                self.limits.max_correction_age_s,
            ),
            (
                "solution_age",
                getattr(native, "solution_age_s", None),
                self.limits.max_solution_age_s,
            ),
        ):
            reason = f"{name}_exceeded"
            if (
                limit is not None
                and value is not None
                and value + age > limit
                and reason not in reasons
            ):
                reasons.append(reason)
        if (
            self._last_unique_at is not None
            and current - self._last_unique_at > self.max_gap_seconds
        ):
            reasons.append("gap_exceeded")
        if self._order_error:
            reasons.append("epoch_not_increasing")
        return reasons

    def observe(
        self,
        position: "Position",
        *,
        now_gps_seconds: float,
        now: float | None = None,
    ) -> ConvergenceStatus:
        """Assess a measurement against a trusted current GPS clock, in seconds."""
        _finite(now_gps_seconds, "now_gps_seconds")
        assessment = assess_position(
            position, self.limits, now_gps_seconds=now_gps_seconds
        )
        current = self._time(now)
        if current - self._started >= self.timeout:
            return self.status(now=current)
        if self._reasons(current):
            self._reset_window()
        self._assessment = assessment
        self._observed_at = current
        stamp = position.receiver_time
        epoch = (
            stamp.gps_seconds
            if stamp is not None and stamp.fine is True and not stamp.assumed_scale
            else None
        )
        if epoch is not None and (
            isinstance(epoch, bool)
            or not isfinite(epoch)
            or epoch < 0
            or "epoch_age_unknown" in assessment.reasons
            or "epoch_age_exceeded" in assessment.reasons
        ):
            epoch = None
        self._order_error = (
            epoch is not None
            and self._last_epoch is not None
            and epoch < self._last_epoch
        )
        if not assessment.accepted or self._order_error or epoch is None:
            self._reset_window()
        if epoch is not None and (self._last_epoch is None or epoch > self._last_epoch):
            if (
                self._last_epoch is not None
                and epoch - self._last_epoch > self.max_gap_seconds
            ):
                self._reset_window()
            self._last_epoch = epoch
            self._last_unique_at = current
            if assessment.accepted:
                if self._first_epoch is None or self._first_at is None:
                    self._first_epoch = epoch
                    self._first_at = current
                self._epochs += 1
                self._span = min(epoch - self._first_epoch, current - self._first_at)
        return self.status(now=current)

    def status(self, *, now: float | None = None) -> ConvergenceStatus:
        """Recheck the window, deadline and freshness without receiving a position."""
        current = self._time(now)
        reasons = self._reasons(current)
        timed_out = current - self._started >= self.timeout
        if reasons or timed_out:
            self._reset_window()
        if timed_out:
            reasons.append("timeout")
        if not reasons:
            if self._epochs < self.min_epochs:
                reasons.append("insufficient_epochs")
            if self._span < self.hold_seconds:
                reasons.append("hold_time_not_reached")
        return ConvergenceStatus(
            self._assessment,
            self._epochs,
            self._span,
            current - self._started,
            timed_out,
            tuple(reasons),
        )
