"""Typed navigation and heading records."""

from dataclasses import dataclass
from math import isfinite
from struct import unpack_from
from typing import Self

from um982py.errors import ProtocolError
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.messages.frames import AsciiMessage, BinaryMessage, Message, Sentence


def _number(value: str) -> float | None:
    if not value:
        return None
    number = float(value)
    if not isfinite(number):
        raise ValueError("Non-finite navigation value")
    return number


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
    differential_age: float | None
    station_id: str

    @property
    def valid(self) -> bool:
        return (
            self.quality > 0
            and self.latitude is not None
            and self.longitude is not None
        )

    @property
    def rtk_fixed(self) -> bool:
        """Whether GGA reports an RTK fixed fix, without assessing correction age."""
        return self.valid and self.quality == 4

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
        fields = message.fields
        if len(fields) < 14:
            raise ProtocolError("Incomplete GGA message")
        try:
            return cls(
                fields[0],
                _coordinate(fields[1], fields[2], latitude=True),
                _coordinate(fields[3], fields[4], latitude=False),
                int(fields[5] or 0),
                int(fields[6] or 0),
                _number(fields[7]),
                _number(fields[8]),
                _number(fields[10]),
                _number(fields[12]),
                fields[13],
            )
        except ValueError as error:
            raise ProtocolError("Invalid GGA value") from error


@dataclass(frozen=True, slots=True)
class Heading:
    degrees: float | None
    valid: bool

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if not isinstance(message, Sentence) or message.kind != "THS":
            raise ProtocolError("Not a THS message")
        if len(message.fields) != 2:
            raise ProtocolError("Expected two THS fields")
        try:
            degrees = _number(message.fields[0])
            if degrees is not None and not 0 <= degrees <= 360:
                raise ValueError("Heading out of range")
            return cls(degrees, message.fields[1] == "A" and degrees is not None)
        except ValueError as error:
            raise ProtocolError("Invalid THS value") from error


@dataclass(frozen=True, slots=True)
class BestNavigation:
    solution_status: str | int
    position_type: str | int
    latitude: float
    longitude: float
    altitude_msl: float
    geoid_separation: float
    satellites_tracked: int
    satellites_used: int
    horizontal_speed: float
    track: float
    vertical_speed: float
    velocity_solution_status: str | int
    velocity_type: str | int
    datum: str | int

    @property
    def valid(self) -> bool:
        """Whether the receiver reports a computed position of a known type."""
        return _computed(self.solution_status, self.position_type, position=True)

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

    @classmethod
    def from_message(cls, message: Message) -> Self:
        if isinstance(message, BinaryMessage) and message.header.message_id in (
            2118,
            2119,
        ):
            payload = message.payload
            if len(payload) != 120:
                raise ProtocolError("Expected 120-byte BESTNAV payload")
            status, kind, lat, lon, height, undulation = unpack_from("<IIdddf", payload)
            speed, track, vertical = unpack_from("<ddd", payload, 88)
            velocity_status, velocity_type = unpack_from("<II", payload, 72)
            datum = unpack_from("<I", payload, 36)[0]
            return cls(
                status,
                kind,
                lat,
                lon,
                height,
                undulation,
                payload[64],
                payload[65],
                speed,
                track,
                vertical,
                velocity_status,
                velocity_type,
                datum,
            )
        if isinstance(message, AsciiMessage) and message.name in (
            "BESTNAVA",
            "BESTNAVHA",
        ):
            fields = message.fields
            if len(fields) < 28:
                raise ProtocolError("Incomplete BESTNAV message")
            try:
                return cls(
                    fields[0],
                    fields[1],
                    float(fields[2]),
                    float(fields[3]),
                    float(fields[4]),
                    float(fields[5]),
                    int(fields[13]),
                    int(fields[14]),
                    float(fields[25]),
                    float(fields[26]),
                    float(fields[27]),
                    fields[21],
                    fields[22],
                    fields[6],
                )
            except ValueError as error:
                raise ProtocolError("Invalid BESTNAV value") from error
        raise ProtocolError("Not a BESTNAV message")


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
