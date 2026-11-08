"""Small adapters for field positions and optional ROS 2 messages."""

from importlib import import_module
from math import isfinite
from typing import Any, Literal, Protocol, cast

from um982py.live import PositionUpdate
from um982py.messages.navigation import Fix


class RosTime(Protocol):
    sec: int
    nanosec: int


class RosHeader(Protocol):
    stamp: RosTime
    frame_id: str


class RosNavSatStatus(Protocol):
    status: int
    service: int


class RosNavSatFix(Protocol):
    COVARIANCE_TYPE_UNKNOWN: int
    header: RosHeader
    status: RosNavSatStatus
    latitude: float
    longitude: float
    altitude: float
    position_covariance_type: int


def geojson_feature(
    update: PositionUpdate, *, reference_frame: Literal["WGS84"]
) -> dict[str, Any] | None:
    """Create a GeoJSON point when the caller has established WGS 84 coordinates."""
    if reference_frame != "WGS84":
        raise ValueError("GeoJSON coordinates must be WGS84")
    fix = update.fix
    if not fix.valid or fix.latitude is None or fix.longitude is None:
        return None
    if (
        not isfinite(fix.latitude)
        or not isfinite(fix.longitude)
        or not -90 <= fix.latitude <= 90
        or not -180 <= fix.longitude <= 180
    ):
        raise ValueError("invalid WGS84 position")
    coordinates = [fix.longitude, fix.latitude]
    height = fix.ellipsoidal_height
    if height is not None:
        if not isfinite(height):
            raise ValueError("invalid ellipsoidal height")
        coordinates.append(height)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": {
            "receiver_utc_time": fix.utc,
            "received_at": update.received_at.isoformat(),
            "quality": fix.quality,
            "satellites": fix.satellites,
            "correction_age_s": fix.differential_age,
            "connection": update.connection,
        },
    }


def navsatfix(
    fix: Fix,
    *,
    stamp: RosTime,
    frame_id: str,
    reference_frame: Literal["WGS84"],
    status: int | None = None,
    service: int = 0,
) -> RosNavSatFix:
    """Build a ROS 2 NavSatFix using an application-supplied ROS timestamp.

    The caller must establish the coordinate frame and any augmentation
    status. By default, only GGA quality 1 is treated as a valid unaugmented
    fix. Constellation and covariance are not inferred from GGA.
    """
    if reference_frame != "WGS84":
        raise ValueError("NavSatFix coordinates must be WGS84")
    if not frame_id:
        raise ValueError("frame_id is required")
    if status is not None and status not in (-1, 0, 1, 2):
        raise ValueError("unsupported NavSatStatus code")
    if not isinstance(service, int) or not 0 <= service <= 65535:
        raise ValueError("service must be an unsigned 16-bit bitmask")
    if status is None:
        status = 0 if fix.valid and fix.quality == 1 else -1
    if status >= 0 and not fix.valid:
        raise ValueError("a valid ROS status requires a valid GGA fix")
    if status >= 0 and (
        fix.latitude is None
        or fix.longitude is None
        or not isfinite(fix.latitude)
        or not isfinite(fix.longitude)
        or not -90 <= fix.latitude <= 90
        or not -180 <= fix.longitude <= 180
    ):
        raise ValueError("invalid WGS84 position")
    try:
        messages = import_module("sensor_msgs.msg")
    except ModuleNotFoundError as error:
        if error.name not in ("sensor_msgs", "sensor_msgs.msg"):
            raise
        raise ImportError("ROS 2 sensor_msgs must be installed and sourced") from error
    message = cast(RosNavSatFix, messages.NavSatFix())
    message.header.stamp = stamp
    message.header.frame_id = frame_id
    message.status.status = status
    message.status.service = service
    message.latitude = (
        fix.latitude if status >= 0 and fix.latitude is not None else float("nan")
    )
    message.longitude = (
        fix.longitude if status >= 0 and fix.longitude is not None else float("nan")
    )
    message.altitude = (
        fix.altitude_msl + fix.geoid_separation
        if status >= 0
        and fix.altitude_msl is not None
        and fix.geoid_separation is not None
        else float("nan")
    )
    if (
        fix.altitude_msl is not None
        and fix.geoid_separation is not None
        and status >= 0
        and not isfinite(message.altitude)
    ):
        raise ValueError("invalid ellipsoidal height")
    message.position_covariance_type = message.COVARIANCE_TYPE_UNKNOWN
    return message
