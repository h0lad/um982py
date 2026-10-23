"""Position tracks from BESTNAV and PPPNAV fixes."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import pairwise

from examples.position_tracking.quality import summary_statistics
from um982py.capture import record_epoch
from um982py.geodesy import haversine_distance
from um982py.messages.enums import PositionType
from um982py.messages.record import Record, Value
from um982py.stats import mean, stddev


@dataclass(frozen=True, slots=True)
class TrackPoint:
    """One fix with coordinates in degrees and MSL altitude in metres (receiver hgt)."""

    timestamp: float
    latitude: float
    longitude: float
    altitude: float
    speed: float | None
    satellites: int
    position_type: str
    source: str = "BESTNAV"
    undulation_m: float | None = None
    height_msl: float | None = None
    height_ellipsoid_m: float | None = None
    latitude_sigma_m: float | None = None
    longitude_sigma_m: float | None = None
    height_sigma_m: float | None = None
    horizontal_sigma_m: float | None = None
    speed_sigma_m_s: float | None = None
    vertical_speed_sigma_m_s: float | None = None
    solution_satellites: int | None = None
    correction_age_s: float | None = None
    solution_age_s: float | None = None
    latency_s: float | None = None

    @classmethod
    def from_record(cls, record: Record, timestamp: float | None = None) -> TrackPoint:
        height = record.real("hgt")
        undulation = _optional_real(record, "undulation")
        lat_sigma = _optional_real(record, "lat_std")
        lon_sigma = _optional_real(record, "lon_std")
        return cls(
            timestamp=record_epoch(record) if timestamp is None else timestamp,
            latitude=record.real("lat"),
            longitude=record.real("lon"),
            altitude=height,
            speed=_optional_real(record, "hor_spd"),
            satellites=record.integer("count_svs"),
            position_type=_label(record["pos_type"]),
            source=record.name,
            undulation_m=undulation,
            height_msl=height,
            height_ellipsoid_m=height + undulation if undulation is not None else None,
            latitude_sigma_m=lat_sigma,
            longitude_sigma_m=lon_sigma,
            height_sigma_m=_optional_real(record, "hgt_std"),
            horizontal_sigma_m=math.hypot(lat_sigma, lon_sigma)
            if lat_sigma is not None and lon_sigma is not None
            else None,
            speed_sigma_m_s=_optional_real(record, "horspd_std"),
            vertical_speed_sigma_m_s=_optional_real(record, "verspd_std"),
            solution_satellites=_optional_int(record, "count_solnsvs"),
            correction_age_s=_optional_real(record, "diff_age"),
            solution_age_s=_optional_real(record, "sol_age"),
            latency_s=_optional_real(record, "latency"),
        )


@dataclass(frozen=True, slots=True)
class SpeedStatistics:
    mean: float
    minimum: float
    maximum: float
    standard_deviation: float


@dataclass(frozen=True, slots=True)
class BoundingBox:
    minimum_latitude: float
    maximum_latitude: float
    minimum_longitude: float
    maximum_longitude: float


@dataclass(frozen=True, slots=True)
class Geofence:
    latitude: float
    longitude: float
    radius: float

    def __post_init__(self) -> None:
        if not self.radius > 0:
            raise ValueError("fence radius must be positive")

    def contains(self, point: TrackPoint) -> bool:
        return (
            haversine_distance(
                self.latitude, self.longitude, point.latitude, point.longitude
            )
            <= self.radius
        )


@dataclass(frozen=True, slots=True)
class Track:
    points: tuple[TrackPoint, ...] = ()

    def with_point(self, point: TrackPoint) -> Track:
        return Track((*self.points, point))

    @property
    def distance(self) -> float:
        return sum(
            (
                haversine_distance(a.latitude, a.longitude, b.latitude, b.longitude)
                for a, b in pairwise(self.points)
            ),
            0.0,
        )

    @property
    def duration(self) -> float:
        if len(self.points) < 2:
            return 0.0
        return self.points[-1].timestamp - self.points[0].timestamp

    @property
    def average_speed(self) -> float:
        duration = self.duration
        return self.distance / duration if duration > 0 else math.nan

    @property
    def speed_statistics(self) -> SpeedStatistics:
        speeds = [point.speed for point in self.points if point.speed is not None]
        return SpeedStatistics(
            mean=mean(speeds),
            minimum=_minimum(speeds),
            maximum=_maximum(speeds),
            standard_deviation=stddev(speeds),
        )

    @property
    def bounds(self) -> BoundingBox:
        latitudes = [point.latitude for point in self.points]
        longitudes = [point.longitude for point in self.points]
        return BoundingBox(
            minimum_latitude=_minimum(latitudes),
            maximum_latitude=_maximum(latitudes),
            minimum_longitude=_minimum(longitudes),
            maximum_longitude=_maximum(longitudes),
        )

    def outside(self, fence: Geofence) -> tuple[TrackPoint, ...]:
        return tuple(point for point in self.points if not fence.contains(point))

    def geojson(self) -> dict[str, object]:
        features: list[dict[str, object]] = []
        if len(self.points) > 1:
            features.append(_path_feature(self.points))
        features.extend(_point_feature(point) for point in self.points)
        return {"type": "FeatureCollection", "features": features}

    def report(self, fence: Geofence | None = None) -> dict[str, object]:
        speeds = self.speed_statistics
        precision_fields = (
            "latitude_sigma_m",
            "longitude_sigma_m",
            "height_sigma_m",
            "horizontal_sigma_m",
            "speed_sigma_m_s",
            "vertical_speed_sigma_m_s",
            "satellites",
            "solution_satellites",
            "correction_age_s",
            "solution_age_s",
            "latency_s",
        )
        return {
            "fixes": len(self.points),
            "fix_classes": dict(Counter(point.position_type for point in self.points)),
            "latest_fix": asdict(self.points[-1]) if self.points else None,
            "positions": [asdict(point) for point in self.points],
            "distance_m": self.distance,
            "duration_s": self.duration,
            "average_speed_m_s": _finite(self.average_speed),
            "speed_m_s": {
                "mean": _finite(speeds.mean),
                "minimum": _finite(speeds.minimum),
                "maximum": _finite(speeds.maximum),
                "standard_deviation": _finite(speeds.standard_deviation),
            },
            "precision_statistics": {
                name: summary_statistics(
                    [
                        float(value)
                        for point in self.points
                        if (value := getattr(point, name)) is not None
                    ]
                )
                for name in precision_fields
            },
            "bounding_box": _bounds_report(self.bounds),
            "outside_fence": len(self.outside(fence)) if fence is not None else None,
        }


def _label(value: Value) -> str:
    if isinstance(value, int):
        try:
            return PositionType(value).name
        except ValueError:
            pass
    return value if isinstance(value, str) else str(value)


def _optional_real(record: Record, key: str) -> float | None:
    value = record.get(key)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _optional_int(record: Record, key: str) -> int | None:
    value = record.get(key)
    return value if isinstance(value, int) else None


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _minimum(values: list[float]) -> float:
    return min(values) if values else math.nan


def _maximum(values: list[float]) -> float:
    return max(values) if values else math.nan


def _bounds_report(bounds: BoundingBox) -> dict[str, float] | None:
    if not math.isfinite(bounds.minimum_latitude):
        return None
    return {
        "minimum_latitude": bounds.minimum_latitude,
        "maximum_latitude": bounds.maximum_latitude,
        "minimum_longitude": bounds.minimum_longitude,
        "maximum_longitude": bounds.maximum_longitude,
    }


def _point_feature(point: TrackPoint) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [point.longitude, point.latitude],
        },
        "properties": {
            "timestamp": point.timestamp,
            "altitude": point.altitude,
            "undulation_m": point.undulation_m,
            "height_msl": point.height_msl,
            "height_ellipsoid_m": point.height_ellipsoid_m,
            "speed": point.speed,
            "satellites": point.satellites,
            "position_type": point.position_type,
            "source": point.source,
            "latitude_sigma_m": point.latitude_sigma_m,
            "longitude_sigma_m": point.longitude_sigma_m,
            "height_sigma_m": point.height_sigma_m,
            "correction_age_s": point.correction_age_s,
        },
    }


def _path_feature(points: tuple[TrackPoint, ...]) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[point.longitude, point.latitude] for point in points],
        },
        "properties": {"fixes": len(points)},
    }
