"""Typed navigation and heading records."""

from contextlib import suppress
from dataclasses import dataclass, field
from math import isfinite
from typing import Protocol, Self, runtime_checkable

from um982py.errors import ProtocolError
from um982py.messages.enums import PositionType, SolutionStatus, _reported_datum
from um982py.messages.frames import AsciiMessage, BinaryMessage, Message, Sentence
from um982py.messages.record import Record, Value


@runtime_checkable
class Position(Protocol):
    """Common position information; unavailable values are None.

    GPS epochs are absolute GPS seconds when the source includes a verified GPS
    week and time. GGA reports UTC time of day without a date, so its epoch is
    unavailable. Source-specific fields remain on each concrete model.
    """

    @property
    def latitude(self) -> float | None: ...

    @property
    def longitude(self) -> float | None: ...

    @property
    def valid(self) -> bool: ...

    @property
    def rtk_fixed(self) -> bool: ...

    @property
    def correction_age_s(self) -> float | None: ...

    @property
    def epoch_gps_seconds(self) -> float | None: ...

    @property
    def satellites_used(self) -> int | None: ...

    @property
    def ellipsoidal_height(self) -> float | None: ...


def _optional_number(value: Value) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ProtocolError("Invalid navigation value")
    number = float(value)
    if not isfinite(number):
        raise ProtocolError("Non-finite navigation value")
    return number


def _standard_deviation(value: Value) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ProtocolError("Invalid BESTNAV position standard deviation")
    number = float(value)
    return number if isfinite(number) and number >= 0 else None


def _enum_value(value: Value) -> str | int:
    if value is None:
        return ""
    if isinstance(value, (str, int)):
        return value
    raise ProtocolError("Invalid BESTNAV enumeration")


def _solution_status(value: str | int) -> SolutionStatus | str | int:
    try:
        return (
            SolutionStatus[value] if isinstance(value, str) else SolutionStatus(value)
        )
    except (KeyError, ValueError):
        return value


def _position_type(value: str | int) -> PositionType | str | int:
    try:
        return PositionType[value] if isinstance(value, str) else PositionType(value)
    except (KeyError, ValueError):
        return value


def _coordinate(value: str, direction: str, *, latitude: bool) -> float | None:
    if not value or not direction:
        return None
    number = float(value)
    degrees, minutes = divmod(number, 100)
    limit = 90 if latitude else 180
    directions = ("N", "S") if latitude else ("E", "W")
    if direction not in directions or not 0 <= minutes < 60:
        raise ValueError("Invalid NMEA coordinate")
    coordinate = degrees + minutes / 60
    if not isfinite(coordinate) or not 0 <= coordinate <= limit:
        raise ValueError("NMEA coordinate out of range")
    return -coordinate if direction in ("S", "W") else coordinate


@dataclass(frozen=True, slots=True)
class Fix:
    utc: str
    latitude: float | None
    longitude: float | None
    quality: int
    satellites: int
    hdop: float | None
    altitude_msl: float | None
    geoid_separation: float | None
    correction_age_s: float | None
    station_id: str
    quality_known: bool = field(default=True, kw_only=True, repr=False)
    satellites_known: bool = field(default=True, kw_only=True, repr=False)

    @property
    def valid(self) -> bool:
        return (
            self.quality > 0
            and self.latitude is not None
            and self.longitude is not None
        )

    @property
    def possibly_predicted(self) -> bool | None:
        """Whether the GGA fix has the receiver's Doppler-prediction signature.

        R1.15 documents quality 1 and zero satellites for Doppler-predicted
        positions. This combination does not prove prediction. Return None when
        a missing quality or satellite count prevents checking the signature.
        """
        if self.latitude is None or self.longitude is None:
            return False
        if self.quality_known and self.quality != 1:
            return False
        if self.satellites_known and self.satellites != 0:
            return False
        if not self.quality_known or not self.satellites_known:
            return None
        return True

    @property
    def rtk_fixed(self) -> bool:
        """Whether GGA reports an RTK fixed fix. Check correction age separately."""
        return self.valid and self.quality == 4

    @property
    def epoch_gps_seconds(self) -> None:
        """GGA contains time of day but no date or GPS week."""
        return None

    @property
    def satellites_used(self) -> int | None:
        return self.satellites if self.satellites_known else None

    @property
    def ellipsoidal_height(self) -> float | None:
        """Height above the ellipsoid in metres when both GGA heights are present."""
        if self.altitude_msl is None or self.geoid_separation is None:
            return None
        return self.altitude_msl + self.geoid_separation

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if not isinstance(message, Sentence) or message.kind not in ("GGA", "GGAH"):
            raise ProtocolError("Not a GGA message")
        from um982py.messages.decode import decode_log

        try:
            return cls.from_record(decode_log(message))
        except ProtocolError as error:
            raise ProtocolError("Invalid GGA value") from error

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Build a fix from a decoded GGA or GGAH record."""
        if record.name[2:] not in ("GGA", "GGAH"):
            raise ProtocolError("Not a GGA record")
        try:
            quality = record["quality"]
            satellites = record["satellites"]
            if quality is not None and not isinstance(quality, int):
                raise TypeError("Invalid quality")
            if satellites is not None and not isinstance(satellites, int):
                raise TypeError("Invalid satellites")
            utc, station_id = record["utc"], record["station_id"]
            if utc is not None and not isinstance(utc, str):
                raise TypeError("Invalid UTC")
            if station_id is not None and not isinstance(station_id, str):
                raise TypeError("Invalid station ID")
            age = _optional_number(record["differential_age"])
            return cls(
                utc or "",
                _optional_number(record["latitude"]),
                _optional_number(record["longitude"]),
                quality if quality is not None else 0,
                satellites if satellites is not None else 0,
                _optional_number(record["hdop"]),
                _optional_number(record["altitude_msl"]),
                _optional_number(record["geoid_separation"]),
                age if age is not None and age >= 0 else None,
                station_id or "",
                quality_known=quality is not None,
                satellites_known=satellites is not None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProtocolError("Invalid GGA value") from error


@dataclass(frozen=True, slots=True)
class Heading:
    degrees: float | None
    valid: bool

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if not isinstance(message, Sentence) or message.kind != "THS":
            raise ProtocolError("Not a THS message")
        from um982py.messages.decode import decode_log

        try:
            return cls.from_record(decode_log(message))
        except ProtocolError as error:
            raise ProtocolError("Invalid THS value") from error

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Build a heading from a decoded THS record."""
        if record.name[2:] != "THS":
            raise ProtocolError("Not a THS record")
        try:
            degrees = _optional_number(record["heading"])
            if degrees is not None and not 0 <= degrees <= 360:
                raise ValueError("Heading out of range")
            return cls(degrees, record["mode"] == "A" and degrees is not None)
        except (KeyError, TypeError, ValueError) as error:
            raise ProtocolError("Invalid THS value") from error


@dataclass(frozen=True, slots=True)
class BestNavigation:
    """Position and velocity with receiver-estimated standard deviations in metres.

    Known status values use the same enums for ASCII and binary messages.
    WGS84 is named consistently across formats. Unknown values retain their
    original representation. The original message is available through ``message``.
    """

    solution_status: SolutionStatus | str | int
    position_type: PositionType | str | int
    latitude: float
    longitude: float
    altitude_msl: float
    geoid_separation: float
    satellites_tracked: int
    satellites_used: int
    horizontal_speed: float
    track: float
    vertical_speed: float
    velocity_solution_status: SolutionStatus | str | int
    velocity_type: PositionType | str | int
    datum: str | int
    latitude_std_m: float | None = None
    longitude_std_m: float | None = None
    height_std_m: float | None = None
    message: AsciiMessage | BinaryMessage | None = field(
        default=None, repr=False, compare=False
    )
    correction_age_s: float | None = field(default=None, kw_only=True)
    epoch_gps_seconds: float | None = field(default=None, kw_only=True)

    @property
    def valid(self) -> bool:
        """Whether the receiver reports a computed position of a known type."""
        return _computed(self.solution_status, self.position_type, position=True)

    @property
    def rtk_fixed(self) -> bool:
        """Whether a computed solution reports a fixed RTK position type."""
        return self.valid and self.position_type in (
            PositionType.L1_INT,
            PositionType.WIDE_INT,
            PositionType.NARROW_INT,
            PositionType.INS_RTKFIXED,
        )

    @property
    def velocity_valid(self) -> bool:
        """Whether the receiver reports a computed velocity of a known type."""
        return _computed(self.velocity_solution_status, self.velocity_type)

    @property
    def ellipsoidal_height(self) -> float:
        """Return ellipsoidal height in metres. Check ``valid`` before using it."""
        return self.altitude_msl + self.geoid_separation

    def __post_init__(self) -> None:
        values = (
            self.latitude,
            self.longitude,
            self.altitude_msl,
            self.geoid_separation,
            self.horizontal_speed,
            self.track,
            self.vertical_speed,
        )
        if not all(isfinite(value) for value in values):
            raise ProtocolError("Non-finite BESTNAV value")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ProtocolError("BESTNAV coordinates out of range")
        if any(
            value is not None and (not isfinite(value) or value < 0)
            for value in (self.latitude_std_m, self.longitude_std_m, self.height_std_m)
        ):
            raise ProtocolError("Invalid BESTNAV position standard deviation")

    @classmethod
    def from_message(cls, message: Message) -> Self:
        from um982py.commands import Log
        from um982py.messages.decode import decode_log

        if isinstance(message, BinaryMessage) and message.header.message_id in (
            2118,
            2119,
        ):
            log = Log.BESTNAV if message.header.message_id == 2118 else Log.BESTNAVH
        elif isinstance(message, AsciiMessage) and message.name in (
            "BESTNAVA",
            "BESTNAVHA",
        ):
            log = Log.BESTNAV if message.name == "BESTNAVA" else Log.BESTNAVH
        else:
            raise ProtocolError("Not a BESTNAV message")
        return cls.from_record(decode_log(message, log=log))

    @classmethod
    def from_record(cls, record: Record) -> Self:
        """Build a navigation model from a decoded BESTNAV or BESTNAVH record."""
        if record.name not in ("BESTNAV", "BESTNAVH"):
            raise ProtocolError("Not a BESTNAV record")
        message = record.message
        try:
            position_type = _position_type(_enum_value(record["pos_type"]))
            solution_status = _solution_status(_enum_value(record["p_sol_status"]))
            age = _optional_number(record.get("diff_age"))
            differential = position_type in (
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
            epoch = None
            if message is not None:
                from um982py.measurement import gps_epoch

                with suppress(ValueError):
                    epoch = gps_epoch(message)
            return cls(
                solution_status,
                position_type,
                record.real("lat"),
                record.real("lon"),
                record.real("hgt"),
                record.real("undulation"),
                record.integer("count_svs"),
                record.integer("count_solnsvs"),
                record.real("hor_spd"),
                record.real("trk_gnd"),
                record.real("vert_spd"),
                _solution_status(_enum_value(record["v_sol_status"])),
                _position_type(_enum_value(record["vel_type"])),
                _reported_datum(_enum_value(record["datum_id"])),
                _standard_deviation(record["lat_std"]),
                _standard_deviation(record["lon_std"]),
                _standard_deviation(record["hgt_std"]),
                message=message
                if isinstance(message, (AsciiMessage, BinaryMessage))
                else None,
                correction_age_s=age
                if differential
                and _computed(solution_status, position_type, position=True)
                and age is not None
                and age >= 0
                else None,
                epoch_gps_seconds=epoch,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProtocolError("Invalid BESTNAV value") from error


def _computed(status: str | int, kind: str | int, *, position: bool = False) -> bool:
    if status not in (SolutionStatus.SOL_COMPUTED, "SOL_COMPUTED"):
        return False
    try:
        position_type = (
            PositionType[kind] if isinstance(kind, str) else PositionType(kind)
        )
    except (KeyError, ValueError):
        return False
    if position and position_type == PositionType.DOPPLER_VELOCITY:
        return False
    return position_type != PositionType.NONE
