"""Small reusable pieces for GGA uplink and RTCM forwarding."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

from um982py import Receiver
from um982py.geodesy import geodetic_from_ecef, haversine_distance
from um982py.messages import RtcmMessage
from um982py.messages.navigation import Fix
from um982py.protocol import StreamDecoder
from um982py.protocol.checksums import nmea_checksum


def _coordinate(value: float, *, latitude: bool) -> tuple[str, str]:
    direction = (
        ("N" if value >= 0 else "S") if latitude else ("E" if value >= 0 else "W")
    )
    magnitude = abs(value)
    # NMEA coordinates use whole degrees followed by minutes in [0, 60).
    # Round the total minutes first so a value near the next degree carries
    # into that degree instead of producing the invalid minute 60.000000.
    micro_minutes = round(magnitude * 60_000_000)
    degrees, remainder = divmod(micro_minutes, 60_000_000)
    minutes, fraction = divmod(remainder, 1_000_000)
    width = 2 if latitude else 3
    return f"{degrees:0{width}d}{minutes:02d}.{fraction:06d}", direction


def gga_from_fix(fix: Fix, *, now: datetime | None = None) -> bytes:
    if not fix.valid or fix.latitude is None or fix.longitude is None:
        raise ValueError("A valid receiver fix is needed for NTRIP GGA")
    moment = now or datetime.now(UTC)
    latitude, north_south = _coordinate(fix.latitude, latitude=True)
    longitude, east_west = _coordinate(fix.longitude, latitude=False)
    hdop = f"{fix.hdop:.1f}" if fix.hdop is not None else ""
    altitude = f"{fix.altitude_msl:.3f}" if fix.altitude_msl is not None else ""
    separation = (
        f"{fix.geoid_separation:.3f}" if fix.geoid_separation is not None else ""
    )
    body = (
        f"GPGGA,{moment:%H%M%S}.00,{latitude},{north_south},"
        f"{longitude},{east_west},{fix.quality},{fix.satellites:02d},"
        f"{hdop},{altitude},M,{separation},M,,"
    ).encode("ascii")
    return b"$" + body + f"*{nmea_checksum(body):02X}\r\n".encode("ascii")


@dataclass(slots=True)
class CorrectionStats:
    bytes_received: int = 0
    frames_forwarded: int = 0
    bytes_forwarded: int = 0
    connection_failures: int = 0
    retry_wait_seconds: float = 0.0
    message_types: Counter[int] = field(default_factory=Counter)
    station: ReferenceStation | None = None
    reference_enabled: bool = False
    station_received_at: float | None = None
    reference_difference_m: float | None = None
    reference_queried_at: float | None = None


@dataclass(frozen=True, slots=True)
class ReferenceStation:
    station_id: int
    latitude: float
    longitude: float
    height_m: float

    @classmethod
    def from_rtcm(cls, message: RtcmMessage) -> ReferenceStation | None:
        if message.message_type not in (1005, 1006):
            return None
        if len(message.payload) != (19 if message.message_type == 1005 else 21):
            return None
        packed = int.from_bytes(message.payload, "big")
        bits = len(message.payload) * 8

        def coordinate(start: int) -> float:
            value = (packed >> (bits - start - 38)) & ((1 << 38) - 1)
            return (value - (1 << 38) if value & (1 << 37) else value) * 0.0001

        latitude, longitude, height = geodetic_from_ecef(
            *(coordinate(start) for start in (34, 74, 114))
        )
        station_id = int.from_bytes(message.payload[:3], "big") & 0xFFF
        return cls(station_id, latitude, longitude, height)

    def distance_km(self, latitude: float, longitude: float) -> float:
        return (
            haversine_distance(self.latitude, self.longitude, latitude, longitude)
            / 1000
        )


def forward_corrections(
    receiver: Receiver,
    data: bytes,
    *,
    decoder: StreamDecoder,
    stats: CorrectionStats,
) -> int:
    stats.bytes_received += len(data)
    forwarded = 0
    for message in decoder.feed(data):
        if not isinstance(message, RtcmMessage):
            continue
        receiver.send_correction(message)
        station = ReferenceStation.from_rtcm(message)
        if station is not None:
            if station != stats.station:
                stats.reference_difference_m = None
                stats.reference_queried_at = None
            stats.station = station
            stats.station_received_at = monotonic()
        stats.frames_forwarded += 1
        stats.bytes_forwarded += len(message.raw)
        if message.message_type is not None:
            stats.message_types[message.message_type] += 1
        forwarded += 1
    return forwarded
