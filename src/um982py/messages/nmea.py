"""NMEA sentence decoding."""

from typing import cast

from um982py.errors import ProtocolError
from um982py.messages.frames import Sentence
from um982py.messages.navigation import _coordinate
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record, Value
from um982py.messages.schema import Field, Kind

SCHEMAS: dict[str, tuple[str, ...]] = {
    "QSM": ("prn:u", "dc_message:s"),
    "DTM": (
        "datum:s",
        "subdivision:s",
        "latitude_offset:f",
        "latitude_direction:s",
        "longitude_offset:f",
        "longitude_direction:s",
        "altitude_offset:f",
        "reference_datum:s",
    ),
    "GBS": (
        "utc:s",
        "latitude_error:f",
        "longitude_error:f",
        "altitude_error:f",
        "satellite_id:u",
        "miss_probability:f",
        "bias:f",
        "bias_std:f",
        "system_id:x",
        "signal_id:x",
    ),
    "GGA": (
        "utc:s",
        "latitude_nmea:d",
        "latitude_direction:s",
        "longitude_nmea:d",
        "longitude_direction:s",
        "quality:u",
        "satellites:u",
        "hdop:f",
        "altitude_msl:f",
        "altitude_unit:s",
        "geoid_separation:f",
        "geoid_unit:s",
        "differential_age:f",
        "station_id:s",
    ),
    "GLL": (
        "latitude_nmea:d",
        "latitude_direction:s",
        "longitude_nmea:d",
        "longitude_direction:s",
        "utc:s",
        "status:s",
        "mode:s",
    ),
    "GNS": (
        "utc:s",
        "latitude_nmea:d",
        "latitude_direction:s",
        "longitude_nmea:d",
        "longitude_direction:s",
        "mode:s",
        "satellites:u",
        "hdop:f",
        "altitude_msl:f",
        "geoid_separation:f",
        "differential_age:f",
        "station_id:s",
        "status:s",
    ),
    "GRS": (
        "utc:s",
        "mode:u",
        *tuple(f"residual_{n}:f" for n in range(1, 13)),
        "system_id:x",
        "signal_id:x",
    ),
    "GSA": (
        "mode:s",
        "fix_type:u",
        *tuple(f"satellite_{n}:u" for n in range(1, 13)),
        "pdop:f",
        "hdop:f",
        "vdop:f",
        "system_id:x",
    ),
    "GST": (
        "utc:s",
        "rms:f",
        "semi_major:f",
        "semi_minor:f",
        "orientation:f",
        "latitude_std:f",
        "longitude_std:f",
        "altitude_std:f",
    ),
    "THS": ("heading:f", "mode:s"),
    "RMC": (
        "utc:s",
        "status:s",
        "latitude_nmea:d",
        "latitude_direction:s",
        "longitude_nmea:d",
        "longitude_direction:s",
        "speed_knots:f",
        "track:f",
        "date:s",
        "magnetic_variation:f",
        "variation_direction:s",
        "mode:s",
        "navigation_status:s",
    ),
    "ROT": ("rate:f", "status:s"),
    "VTG": (
        "true_course:f",
        "true_indicator:s",
        "magnetic_course:f",
        "magnetic_indicator:s",
        "speed_knots:f",
        "knots_indicator:s",
        "speed_kmh:f",
        "kmh_indicator:s",
        "mode:s",
    ),
    "ZDA": ("utc:s", "day:u", "month:u", "year:u", "zone_hours:i", "zone_minutes:i"),
    "HPR": (
        "utc:s",
        "heading:f",
        "pitch:f",
        "roll:f",
        "quality:u",
        "satellites:u",
        "differential_age:f",
        "station_id:s",
    ),
    "TRA2": (
        "utc:s",
        "heading:f",
        "pitch:f",
        "roll:f",
        "quality:u",
        "satellites:u",
        "differential_age:f",
        "station_id:s",
    ),
    "HPD": (
        "gps_week:u",
        "gps_time:d",
        "heading:f",
        "pitch:f",
        "track:f",
        "latitude:d",
        "longitude:d",
        "altitude:f",
        "east_velocity:f",
        "north_velocity:f",
        "up_velocity:f",
        "east_velocity_difference:f",
        "north_velocity_difference:f",
        "up_velocity_difference:f",
        "baseline:f",
        "master_satellites:u",
        "slave_satellites:u",
    ),
    "KSXT": (
        "utc:s",
        "longitude:d",
        "latitude:d",
        "altitude_msl:f",
        "heading:f",
        "pitch:f",
        "track:f",
        "speed_kmh:f",
        "roll:f",
        "position_quality:u",
        "heading_quality:u",
        "slave_satellites:u",
        "master_satellites:u",
        "east:f",
        "north:f",
        "up:f",
        "east_velocity:f",
        "north_velocity:f",
        "up_velocity:f",
        "reserved:s",
        "reserved_2:s",
    ),
}
MINIMUM = {"GBS": 8, "GSA": 17, "GRS": 14, "RMC": 12}


def _field(specification: str) -> Field:
    name, kind = specification.split(":")
    return Field(name, cast(Kind, kind), 0, 4)


def decode_nmea(message: Sentence) -> Record:
    kind = message.kind if message.name != "KSXT" else "KSXT"
    if kind.endswith("H") and kind[:-1] in SCHEMAS | {"GSV": ()}:
        kind = kind[:-1]
    if kind in ("THS2", "ROT2", "HPR2"):
        kind = kind[:-1]
    if kind == "GSV":
        return _gsv(message)
    try:
        schema = SCHEMAS[kind]
    except KeyError as error:
        raise ProtocolError(f"Unknown NMEA sentence: {message.name}") from error
    fields = message.fields
    if not MINIMUM.get(kind, len(schema)) <= len(fields) <= len(schema):
        raise ProtocolError(f"Invalid {kind} field count: {len(fields)}")
    reader = BodyReader(fields + ("",) * (len(schema) - len(fields)))
    entries: list[tuple[str, Value]] = [
        (spec.split(":")[0], reader.scalar(_field(spec), 0)) for spec in schema
    ]
    if kind in ("GGA", "GLL", "GNS", "RMC"):
        lat_index = 0 if kind == "GLL" else 2 if kind == "RMC" else 1
        try:
            latitude = _coordinate(
                fields[lat_index], fields[lat_index + 1], latitude=True
            )
            longitude = _coordinate(
                fields[lat_index + 2], fields[lat_index + 3], latitude=False
            )
        except ValueError as error:
            raise ProtocolError("Invalid NMEA coordinates") from error
        entries.extend((("latitude", latitude), ("longitude", longitude)))
    return Record(message.name, tuple(entries), message)


def _gsv(message: Sentence) -> Record:
    fields = message.fields
    if len(fields) < 3 or len(fields) % 4 not in (0, 3):
        raise ProtocolError("Invalid GSV field count")
    reader = BodyReader(fields)
    header = tuple(
        (name, reader.scalar(Field(name, "u", 0, 1), 0))
        for name in ("total_messages", "message_number", "satellites_visible")
    )
    record = Record(message.name, header)
    total, number = record.integer("total_messages"), record.integer("message_number")
    if not 1 <= number <= total <= 99:
        raise ProtocolError("Invalid GSV sequence")
    count = (len(fields) - 3) // 4
    if count > 4:
        raise ProtocolError("More than four GSV satellites")
    satellites = tuple(
        Record(
            "satellite",
            tuple(
                (name, reader.scalar(Field(name, "u", 0, 2), 0))
                for name in ("prn", "elevation", "azimuth", "snr")
            ),
        )
        for _ in range(count)
    )
    signal: Value = (
        reader.scalar(Field("signal_id", "x", 0, 1), 0)
        if len(fields) % 4 == 0
        else None
    )
    return Record(
        message.name,
        (*header, ("satellites", satellites), ("signal_id", signal)),
        message,
    )
