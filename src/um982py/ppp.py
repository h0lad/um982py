"""Configure satellite PPP and read its position solutions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import IntEnum
from math import isfinite
from threading import Event
from time import sleep
from typing import TYPE_CHECKING, Literal, cast

from um982py._polling import validate_callback, validate_interval
from um982py.augmentation import HIGH_ACCURACY_SIGNAL_GROUP
from um982py.commands import Log, queries
from um982py.commands.configuration import SignalGroup, ppp, signal_group
from um982py.errors import ProtocolError
from um982py.measurement import gps_epoch
from um982py.messages.enums import PositionType, SolutionStatus, _reported_datum
from um982py.messages.frames import AsciiMessage, Message
from um982py.messages.record import Record, Value
from um982py.precision import PositionPrecision

if TYPE_CHECKING:
    from um982py.receiver import Receiver

__all__ = ["PppService", "PppSession", "PppSolution"]

PppService = Literal["AUTO", "E6-HAS", "B2B-PPP", "L6MDCPPP"]
_PPP_TYPES = frozenset(
    (
        PositionType.PPP_CONVERGING,
        PositionType.PPP,
        PositionType.PPP_AR,
        PositionType.PPP_RTK,
    )
)


def _enum_or_raw_value[T: IntEnum](value: Value, enum: type[T]) -> T | int | str | None:
    if isinstance(value, str):
        try:
            return enum[value]
        except KeyError:
            return value
    if type(value) is int:
        try:
            return enum(value)
        except ValueError:
            return value
    return None


def _finite_number(
    record: Record, name: str, *, nonnegative: bool = False
) -> float | None:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) and (not nonnegative or number >= 0) else None


def _nonnegative_integer(record: Record, name: str) -> int | None:
    value = record.get(name)
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True, slots=True)
class PppSolution:
    """One receiver PPPNAV solution and its estimated precision.

    Check ``valid`` before using the coordinates. Selecting a service does not
    establish which corrections the receiver used. Check the receiver's output
    for that evidence. ``datum`` holds the label reported by the receiver.
    Verify the configured PPP datum to establish the coordinate system.
    """

    latitude: float | None
    longitude: float | None
    altitude_msl: float | None
    geoid_separation: float | None
    solution_status: SolutionStatus | int | str | None
    position_type: PositionType | int | str | None
    latitude_std_m: float | None
    longitude_std_m: float | None
    height_std_m: float | None
    correction_age_s: float | None
    solution_age_s: float | None
    satellites_tracked: int | None
    satellites_used: int | None
    datum: Value
    epoch_gps_seconds: float | None
    record: Record

    @property
    def valid(self) -> bool:
        return (
            self.solution_status == SolutionStatus.SOL_COMPUTED
            and self.position_type in _PPP_TYPES
            and self.latitude is not None
            and self.longitude is not None
            and -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
        )

    @property
    def converged(self) -> bool:
        """Whether the receiver reports a computed PPP solution beyond convergence."""
        return self.valid and self.position_type in (
            PositionType.PPP,
            PositionType.PPP_AR,
            PositionType.PPP_RTK,
        )

    @property
    def rtk_fixed(self) -> bool:
        """PPP solution types are not reported as a conventional RTK fixed fix."""
        return False

    @property
    def precision(self) -> PositionPrecision | None:
        """Receiver-reported axis deviations for a computed PPP solution."""
        if not self.valid:
            return None
        result = PositionPrecision(
            source=self.record.name,
            east_std_m=self.longitude_std_m,
            north_std_m=self.latitude_std_m,
            up_std_m=self.height_std_m,
            epoch_gps_seconds=self.epoch_gps_seconds
            if self.epoch_gps_seconds is not None and isfinite(self.epoch_gps_seconds)
            else None,
            antenna=2 if self.record.name == "PPPNAVH" else 1,
        )
        return result if result.available else None

    @property
    def ellipsoidal_height(self) -> float | None:
        if self.altitude_msl is None or self.geoid_separation is None:
            return None
        return self.altitude_msl + self.geoid_separation

    @classmethod
    def from_record(cls, record: Record) -> PppSolution:
        if record.name not in ("PPPNAV", "PPPNAVH"):
            raise ValueError("expected a PPPNAV or PPPNAVH record")
        try:
            epoch = gps_epoch(record.message) if record.message is not None else None
        except ValueError:
            epoch = None
        return cls(
            latitude=_finite_number(record, "lat"),
            longitude=_finite_number(record, "lon"),
            altitude_msl=_finite_number(record, "hgt"),
            geoid_separation=_finite_number(record, "undulation"),
            solution_status=_enum_or_raw_value(
                record.get("sol_status"), SolutionStatus
            ),
            position_type=_enum_or_raw_value(record.get("pos_type"), PositionType),
            latitude_std_m=_finite_number(record, "lat_std", nonnegative=True),
            longitude_std_m=_finite_number(record, "lon_std", nonnegative=True),
            height_std_m=_finite_number(record, "hgt_std", nonnegative=True),
            correction_age_s=_finite_number(record, "diff_age", nonnegative=True),
            solution_age_s=_finite_number(record, "sol_age", nonnegative=True),
            satellites_tracked=_nonnegative_integer(record, "count_svs"),
            satellites_used=_nonnegative_integer(record, "count_solnsvs"),
            datum=_reported_datum(record.get("datum_id")),
            epoch_gps_seconds=epoch,
            record=record,
        )


@dataclass(frozen=True, slots=True)
class PppSession:
    """Active PPP configuration and a receiver used for polling solutions.

    The caller owns the receiver. Configuration remains active when iteration
    ends. A changed signal group is saved automatically by the receiver; the
    PPP service is not explicitly saved.
    If the requested service is already active, an existing ``ONLY`` setting
    remains in effect. Selecting a service does not establish which corrections
    the receiver used; check its output for that evidence.
    """

    receiver: Receiver
    service: PppService
    previous_group: SignalGroup
    active_group: SignalGroup
    previous_enabled: bool | None
    previous_service: str | None
    group_changed: bool
    service_changed: bool

    def position(self, *, binary: bool | None = None) -> PppSolution:
        """Read the current PPP solution once."""
        return PppSolution.from_record(
            self.receiver.read_log(Log.PPPNAV, binary=binary)
        )

    def _poll_position(
        self, on_message: Callable[[Message], None] | None = None
    ) -> PppSolution:
        record = self.receiver._poll_query(Log.PPPNAV.read(binary=True), on_message)
        return PppSolution.from_record(record)

    def poll_positions(
        self,
        *,
        interval: float = 1.0,
        stop: Event | None = None,
        on_message: Callable[[Message], None] | None = None,
    ) -> Iterator[PppSolution]:
        """Poll PPP positions until stopped, interrupted, or the iterator is closed.

        Other messages received during a query go to ``on_message`` or are
        discarded. Previously queued messages remain available to ``receive``.
        The callback runs within the transaction and must not use the receiver.
        """
        validate_interval(interval)
        validate_callback(on_message)
        while stop is None or not stop.is_set():
            yield self._poll_position(on_message)
            if stop is not None:
                if stop.wait(interval):
                    return
            else:
                sleep(interval)


def _start_ppp(receiver: Receiver, *, service: PppService = "E6-HAS") -> PppSession:
    """Enable a satellite PPP service and verify the current receiver settings.

    Changes are limited to signal group and PPP service. Switching to group 3/6
    resets the receiver and is saved automatically. The reset can discard other
    unsaved settings. Group 7/0 remains for B2B-PPP only after base mode is
    verified, and an active service keeps its ``ONLY`` setting. PPP service
    changes are not explicitly saved. Previous settings are not restored.
    """
    if not isinstance(service, str):
        raise ValueError("service must be AUTO, E6-HAS, B2B-PPP, or L6MDCPPP")
    requested = service.upper()
    if requested not in ("AUTO", "E6-HAS", "B2B-PPP", "L6MDCPPP"):
        raise ValueError("service must be AUTO, E6-HAS, B2B-PPP, or L6MDCPPP")
    service = cast(PppService, requested)
    command = ppp(service=service)
    initial = receiver.configuration()
    previous = initial.signal_group
    if previous is None:
        raise ProtocolError("receiver did not report its signal group")
    if previous == SignalGroup(7, 0) and service == "B2B-PPP":
        mode = receiver.execute(queries.mode())
        fields = mode.fields if isinstance(mode, AsciiMessage) else ()
        parts = fields[0].upper().split() if fields else []
        if parts[:2] in (["MODE", "ROVER"], ["MODE", "HEADING"], ["MODE", "HEADING2"]):
            raise ProtocolError("B2B-PPP in signal group 7/0 requires base mode")
        if parts[:2] != ["MODE", "BASE"]:
            raise ProtocolError("cannot verify receiver mode for B2B-PPP in group 7/0")
    current = initial
    active = previous
    attempted: list[str] = []
    try:
        compatible_group = previous == HIGH_ACCURACY_SIGNAL_GROUP or (
            previous == SignalGroup(7, 0) and service == "B2B-PPP"
        )
        if not compatible_group:
            group_command = signal_group(
                HIGH_ACCURACY_SIGNAL_GROUP.master, HIGH_ACCURACY_SIGNAL_GROUP.slave
            )
            attempted.append(group_command.text)
            receiver.execute(group_command)
            current = receiver.configuration()
            readback = current.signal_group
            if readback != HIGH_ACCURACY_SIGNAL_GROUP:
                raise ProtocolError(
                    f"signal group readback is {readback!r}, expected 3/6"
                )
            active = readback
        service_changed = (
            current.ppp_enabled is not True or current.ppp_service != service
        )
        if service_changed:
            attempted.append(command.text)
            receiver.execute(command)
            current = receiver.configuration()
            if current.signal_group != active:
                raise ProtocolError(
                    f"signal group changed during PPP setup: {current.signal_group!r}"
                )
            if current.ppp_enabled is not True or current.ppp_service != service:
                raise ProtocolError(
                    "PPP readback did not confirm the requested service "
                    f"({current.ppp_enabled!r}, {current.ppp_service!r})"
                )
    except BaseException as error:
        if attempted:
            error.add_note(
                f"Before PPP setup: signal group {previous!r}, "
                f"PPP enabled {initial.ppp_enabled!r}, "
                f"service {initial.ppp_service!r}. "
                f"Last verified signal group {current.signal_group!r}, PPP enabled "
                f"{current.ppp_enabled!r}, service {current.ppp_service!r}. "
                "PPP setup attempted "
                + ", ".join(attempted)
                + ". Receiver settings may have changed; inspect its configuration."
            )
        raise
    return PppSession(
        receiver=receiver,
        service=service,
        previous_group=previous,
        active_group=active,
        previous_enabled=initial.ppp_enabled,
        previous_service=initial.ppp_service,
        group_changed=active != previous,
        service_changed=service_changed,
    )
