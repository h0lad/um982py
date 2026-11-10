"""Use position, heading and NTRIP corrections together in one rover session."""

from collections.abc import Iterator
from dataclasses import dataclass
from math import isfinite
from threading import Event, Thread
from time import sleep
from types import TracebackType
from typing import Literal, Self

from um982py.commands import Log, queries
from um982py.commands.core import Command
from um982py.errors import ResponseTimeout
from um982py.measurement import gps_epoch
from um982py.messages.enums import PositionType
from um982py.messages.navigation import BestNavigation, Fix
from um982py.messages.record import Record
from um982py.receiver import Receiver
from um982py.rtk_session import RtkHealth, RtkSession
from um982py.streaming import ReceiverStream
from um982py.survey import SurveyPoint, survey_point, wait_for_fix


@dataclass(frozen=True, slots=True)
class RoverPosition:
    """Position and a receiver-time-matched antenna baseline attitude.

    Heading is clockwise from true north. Apply the installation's antenna
    offset to obtain the vehicle's forward heading. ``heading_offset_s`` is the
    heading epoch minus the position epoch, not transport latency.
    """

    position: BestNavigation
    heading_deg: float | None
    pitch_deg: float | None
    heading_offset_s: float | None
    heading_type: PositionType | None
    correction_age_s: float | None


def _attitude(
    position: BestNavigation, heading: Record, tolerance: float
) -> tuple[float | None, float | None, float | None, PositionType | None]:
    if not position.valid or position.message is None or heading.message is None:
        return None, None, None, None
    if heading["sol_stat"] not in (0, "SOL_COMPUTED"):
        return None, None, None, None
    try:
        raw_type = heading["pos_type"]
        if isinstance(raw_type, str):
            kind = PositionType[raw_type]
        elif isinstance(raw_type, int):
            kind = PositionType(raw_type)
        else:
            return None, None, None, None
        if kind not in (
            PositionType.L1_FLOAT,
            PositionType.IONOFREE_FLOAT,
            PositionType.NARROW_FLOAT,
            PositionType.L1_INT,
            PositionType.WIDE_INT,
            PositionType.NARROW_INT,
        ):
            return None, None, None, None
        offset = gps_epoch(heading.message) - gps_epoch(position.message)
        angle, pitch, length = (
            heading.real(key) for key in ("heading", "pitch", "length")
        )
    except (TypeError, ValueError, KeyError):
        return None, None, None, None
    if (
        abs(offset) > tolerance
        or not all(isfinite(v) for v in (offset, angle, pitch, length))
        or not 0 <= angle <= 360
        or not -90 <= pitch <= 90
        or length <= 0
    ):
        return None, None, None, None
    return angle % 360, pitch, offset, kind


class Rover:
    """Own a receiver stream and optionally relay NTRIP in the background.

    Configure the receiver as a rover first. This session polls BESTNAV and,
    optionally, UNIHEADING; it does not change the receiver configuration.
    The supplied receiver remains open unless ``close_receiver`` is true.
    Fatal correction errors are raised on the next position query and are also
    available through ``correction_health``. Closing waits for in-flight I/O.
    """

    def __init__(
        self,
        receiver: Receiver,
        *,
        ntrip_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        ntrip_version: Literal[1, 2] = 2,
        close_receiver: bool = False,
    ) -> None:
        if ntrip_url is None and (username is not None or password is not None):
            raise ValueError("credentials require an NTRIP URL")
        self.receiver = receiver
        self.stream = ReceiverStream(receiver)
        self._rtk = (
            RtkSession.from_url(
                self.stream,
                ntrip_url,
                username=username,
                password=password,
                version=ntrip_version,
            )
            if ntrip_url is not None
            else None
        )
        self._close_receiver = close_receiver
        self._stop = Event()
        self._thread: Thread | None = None
        self._failure: Exception | None = None
        self._started = False
        self._closed = False

    @classmethod
    def connect(
        cls,
        target: str,
        baudrate: int = 115200,
        *,
        timeout: float = 3,
        ntrip_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        ntrip_version: Literal[1, 2] = 2,
    ) -> Self:
        """Open a serial port or TCP gateway for use as a context manager."""
        receiver = Receiver.connect(target, baudrate, timeout=timeout)
        try:
            return cls(
                receiver,
                ntrip_url=ntrip_url,
                username=username,
                password=password,
                ntrip_version=ntrip_version,
                close_receiver=True,
            )
        except BaseException:
            receiver.close()
            raise

    def __enter__(self) -> Self:
        if self._started or self._closed:
            raise RuntimeError("rover session cannot be restarted")
        try:
            self.stream.start()
        except BaseException:
            if self._close_receiver:
                self.receiver.close()
            self._closed = True
            raise
        self._started = True
        if self._rtk is not None:
            self._thread = Thread(
                target=self._run_corrections, name="um982py-rtk", daemon=True
            )
            try:
                self._thread.start()
            except BaseException:
                self.close()
                raise
        return self

    def _run_corrections(self) -> None:
        if self._rtk is None:
            return
        try:
            self._rtk.run(self._stop)
        except Exception as error:
            self._failure = error

    def _check(self) -> None:
        if not self._started or self._closed:
            raise RuntimeError("rover session is not running")
        if self._failure is not None:
            raise RuntimeError("NTRIP correction relay failed") from self._failure

    def correction_health(self) -> RtkHealth | None:
        """Return relay status; None means corrections were not requested."""
        return self._rtk.health() if self._rtk is not None else None

    @property
    def timeout(self) -> float:
        """Timeout of the underlying receiver queries."""
        return self.receiver.timeout

    def _fix_query(self, command: Command[Fix], *, timeout: float) -> Fix:
        self._check()
        result = self.stream.execute(command, timeout=timeout).result()
        self._check()
        return result

    def wait_for_fix(
        self,
        *,
        timeout: float = 120,
        interval: float = 1,
        rtk_fixed: bool = False,
        max_correction_age: float | None = None,
        antenna: int = 1,
    ) -> Fix:
        """Wait for a GGA fix while background corrections continue."""
        return wait_for_fix(
            _RoverFixReader(self),
            timeout=timeout,
            interval=interval,
            rtk_fixed=rtk_fixed,
            max_correction_age=max_correction_age,
            antenna=antenna,
        )

    def survey_point(
        self,
        *,
        duration: float = 60,
        interval: float = 1,
        rtk_fixed: bool = False,
        max_correction_age: float | None = None,
        antenna: int = 1,
    ) -> SurveyPoint:
        """Survey a stationary point while background corrections continue."""
        return survey_point(
            _RoverFixReader(self),
            duration=duration,
            interval=interval,
            rtk_fixed=rtk_fixed,
            max_correction_age=max_correction_age,
            antenna=antenna,
        )

    def position(
        self, *, heading: bool = True, heading_tolerance: float = 0.5
    ) -> RoverPosition:
        """Poll one position and optionally a heading from a nearby receiver epoch."""
        if (
            isinstance(heading_tolerance, bool)
            or not isfinite(heading_tolerance)
            or heading_tolerance < 0
        ):
            raise ValueError("heading_tolerance must be finite and non-negative")
        self._check()
        position = self.stream.execute(queries.best_navigation()).result()
        angle = pitch = offset = None
        heading_type = None
        if heading:
            try:
                attitude = self.stream.execute(Log.UNIHEADING.read()).result()
            except ResponseTimeout:
                pass
            else:
                angle, pitch, offset, heading_type = _attitude(
                    position, attitude, heading_tolerance
                )
        age = None
        differential_types = (
            PositionType.PSRDIFF,
            PositionType.L1_FLOAT,
            PositionType.IONOFREE_FLOAT,
            PositionType.NARROW_FLOAT,
            PositionType.L1_INT,
            PositionType.WIDE_INT,
            PositionType.NARROW_INT,
            PositionType.INS_PSRDIFF,
            PositionType.INS_RTKFLOAT,
            PositionType.INS_RTKFIXED,
        )
        if (
            position.valid
            and position.position_type in differential_types
            and position.message is not None
        ):
            value = Log.BESTNAV.decode(position.message).real("diff_age")
            if isfinite(value) and value >= 0:
                age = value
        self._check()
        return RoverPosition(position, angle, pitch, offset, heading_type, age)

    def positions(
        self,
        *,
        interval: float = 1,
        heading: bool = True,
        heading_tolerance: float = 0.5,
        stop: Event | None = None,
    ) -> Iterator[RoverPosition]:
        """Poll positions until the caller stops iteration or signals ``stop``."""
        if isinstance(interval, bool) or not isfinite(interval) or interval <= 0:
            raise ValueError("interval must be finite and positive")
        while stop is None or not stop.is_set():
            yield self.position(heading=heading, heading_tolerance=heading_tolerance)
            if stop is None:
                sleep(interval)
            elif stop.wait(interval):
                return

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join()
        try:
            self.stream.close()
        finally:
            if self._close_receiver:
                self.receiver.close()
            self._closed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _RoverFixReader:
    def __init__(self, rover: Rover) -> None:
        self.rover = rover
        self.timeout = rover.timeout

    def execute(self, command: Command[Fix], *, timeout: float) -> Fix:
        return self.rover._fix_query(command, timeout=timeout)
