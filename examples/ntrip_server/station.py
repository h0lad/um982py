"""Validates reference coordinates and RTCM station frames."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from um982py.commands import logging, modes
from um982py.commands.configuration.antenna import antenna_delta
from um982py.commands.core import Command
from um982py.errors import ProtocolError
from um982py.geodesy import ecef_from_geodetic
from um982py.messages import CommandResponse, RtcmMessage

RTCM_INTERVALS = ((1005, 5), (1074, 1), (1094, 1), (1124, 1))
OBSERVATION_TYPES = frozenset((1074, 1094, 1124))


@dataclass(frozen=True, slots=True)
class Station:
    """Holds an operator-reviewed ARP position with its frame and epoch."""

    mountpoint: str
    station_id: int
    latitude: float
    longitude: float
    height: float
    reference_frame: str
    coordinate_epoch: float
    source_report: str
    position_verified: bool
    reference_point: str = "ARP"
    country: str = "DEU"
    carrier: int = 2
    bitrate: int = 9600

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.mountpoint):
            raise ValueError("mountpoint needs 1..64 letters, digits, '_' or '-'")
        if self.mountpoint == "healthz":
            raise ValueError("healthz is reserved for readiness checks")
        if type(self.station_id) is not int or not 0 <= self.station_id <= 4095:
            raise ValueError("station_id must be in 0..4095")
        for name, low, high in (
            ("latitude", -90, 90),
            ("longitude", -180, 180),
            ("height", -1000, 10000),
            ("coordinate_epoch", 1980, 2100),
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and in {low}..{high}")
        for name in ("reference_frame", "source_report"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise ValueError(f"{name} must identify the reviewed solution")
        if self.position_verified is not True or self.reference_point != "ARP":
            raise ValueError("review the position and supply ARP coordinates")
        if not re.fullmatch(r"[A-Z]{3}", self.country):
            raise ValueError("country needs a three-letter uppercase code")
        if type(self.carrier) is not int or self.carrier not in (0, 1, 2):
            raise ValueError("carrier must be 0, 1 or 2")
        if type(self.bitrate) is not int or not 0 <= self.bitrate <= 10_000_000:
            raise ValueError("bitrate must be an integer in 0..10000000")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("station manifest must be a JSON object")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError("station manifest has invalid fields or types") from error

    def build_commands(self) -> tuple[Command[CommandResponse], ...]:
        """Configure ECEF base coordinates so RTCM 1005 keeps the reviewed ARP."""
        x, y, z = ecef_from_geodetic(self.latitude, self.longitude, self.height)
        return (
            modes.base_ecef(x, y, z, station_id=self.station_id),
            antenna_delta(0, 0, 0),
            *(logging.output(f"RTCM{kind}", rate) for kind, rate in RTCM_INTERVALS),
        )

    def build_sourcetable(self, *, public: bool) -> bytes:
        authentication = "N" if public else "B"
        details = ",".join(f"{kind}({rate})" for kind, rate in RTCM_INTERVALS)
        return (
            f"STR;{self.mountpoint};{self.mountpoint};RTCM 3.2;{details};"
            f"{self.carrier};"
            f"GPS+GAL+BDS;um982py;{self.country};{self.latitude:.5f};"
            f"{self.longitude:.5f};0;0;um982py;none;{authentication};N;{self.bitrate};\r\n"
            "ENDSOURCETABLE\r\n"
        ).encode("ascii")

    def validate_frame(self, message: RtcmMessage) -> bool:
        """Reject mixed stations and inconsistent RTCM 1005 ARP coordinates."""
        if message.message_type not in (1005, *OBSERVATION_TYPES):
            return False
        payload = message.payload
        if len(payload) < 3:
            raise ProtocolError("RTCM station header is truncated")
        station_id = int.from_bytes(payload[:3], "big") & 0xFFF
        if station_id != self.station_id:
            raise ValueError("RTCM station ID differs from the station manifest")
        if message.message_type == 1005:
            if len(payload) != 19:
                raise ProtocolError("RTCM 1005 needs a 19-byte payload")
            packed = int.from_bytes(payload, "big")

            def coordinate(start: int) -> float:
                value = (packed >> (152 - start - 38)) & ((1 << 38) - 1)
                return (value - (1 << 38) if value & (1 << 37) else value) * 0.0001

            actual = tuple(coordinate(start) for start in (34, 74, 114))
            expected = ecef_from_geodetic(self.latitude, self.longitude, self.height)
            if math.dist(actual, expected) > 0.02:
                raise ValueError("RTCM 1005 ARP differs from the manifest by > 2 cm")
        else:
            # MSM4 identifies satellites and signals with bit masks. Each set
            # bit in their product-sized cell mask identifies one observation.
            # The payload then needs 18 bits per satellite and 48 per active
            # cell, after the 169-bit header. This checks length, not whether
            # the measured ranges or carrier phases are physically correct.
            bits = len(payload) * 8
            if bits < 169:
                raise ProtocolError("RTCM MSM4 header is truncated")
            packed = int.from_bytes(payload, "big")
            satellites = ((packed >> (bits - 137)) & ((1 << 64) - 1)).bit_count()
            signals = ((packed >> (bits - 169)) & ((1 << 32) - 1)).bit_count()
            mask_size = satellites * signals
            if bits < 169 + mask_size:
                raise ProtocolError("RTCM MSM4 cell mask is truncated")
            cells = (
                (packed >> (bits - 169 - mask_size)) & ((1 << mask_size) - 1)
            ).bit_count()
            if bits < 169 + mask_size + 18 * satellites + 48 * cells:
                raise ProtocolError("RTCM MSM4 observations are truncated")
        return True
