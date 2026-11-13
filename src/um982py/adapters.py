"""Small adapters for field positions and optional ROS 2 messages."""

from importlib import import_module
from math import isfinite
from typing import Any, Literal, Protocol, cast

from um982py.live import PositionUpdate
from um982py.messages.enums import PositionType
from um982py.messages.navigation import BestNavigation, Fix


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
    COVARIANCE_TYPE_DIAGONAL_KNOWN: int
    header: RosHeader
    status: RosNavSatStatus
    latitude: float
    longitude: float
    altitude: float
    position_covariance: list[float]
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
            "correction_age_s": fix.correction_age_s,
            "connection": update.connection,
        },
    }


def navsatfix(
    fix: Fix | BestNavigation,
    *,
    stamp: RosTime,
    frame_id: str,
    reference_frame: Literal["WGS84"],
    status: int | None = None,
    service: int = 0,
) -> RosNavSatFix:
    """Build a ROS 2 NavSatFix using an application-supplied ROS timestamp.

    Supply the frame, augmentation status and service mask. By default, only
    unaugmented GGA quality 1 or BESTNAV SINGLE is reported as a valid fix;
    other solution types require an explicit status. BESTNAV standard deviations
    produce an ENU diagonal covariance when all three are available. The
    receiver reports estimates, not an independently verified error bound.
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
        unaugmented = (
            fix.quality == 1
            if isinstance(fix, Fix)
            else fix.position_type in (PositionType.SINGLE, "SINGLE")
        )
        status = 0 if fix.valid and unaugmented else -1
    if status >= 0 and not fix.valid:
        raise ValueError("a valid ROS status requires a valid position")
    if status >= 0 and isinstance(fix, BestNavigation) and fix.datum != "WGS84":
        raise ValueError("BESTNAV datum must be WGS84")
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
    height = fix.ellipsoidal_height if status >= 0 else None
    message.altitude = height if height is not None else float("nan")
    if height is not None and not isfinite(height):
        raise ValueError("invalid ellipsoidal height")
    message.position_covariance_type = message.COVARIANCE_TYPE_UNKNOWN
    if status >= 0 and isinstance(fix, BestNavigation):
        east, north, up = fix.longitude_std_m, fix.latitude_std_m, fix.height_std_m
        if east is not None and north is not None and up is not None:
            variances = (east * east, north * north, up * up)
            if not all(isfinite(value) for value in variances):
                raise ValueError("position covariance exceeds float range")
            message.position_covariance = [
                variances[0],
                0.0,
                0.0,
                0.0,
                variances[1],
                0.0,
                0.0,
                0.0,
                variances[2],
            ]
            message.position_covariance_type = message.COVARIANCE_TYPE_DIAGONAL_KNOWN
    return message
