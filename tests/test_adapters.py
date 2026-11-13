from dataclasses import replace
from datetime import UTC, datetime
from math import isnan
from types import SimpleNamespace

import pytest

from test_bodies import manual_message
from um982py.adapters import geojson_feature, navsatfix
from um982py.live import PositionUpdate
from um982py.messages import BestNavigation, decode_log
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.messages.navigation import Fix


def fix(quality: int = 1) -> Fix:
    return Fix("120000", 50, 8, quality, 10, 1, 100, 45, 1, "base")


def test_geojson_uses_longitude_latitude_and_ellipsoidal_height() -> None:
    update = PositionUpdate(fix(), datetime(2020, 1, 1, tzinfo=UTC), 1, None, 1)
    feature = geojson_feature(update, reference_frame="WGS84")
    assert feature is not None
    assert feature["geometry"]["coordinates"] == [8, 50, 145]
    assert feature["properties"]["receiver_utc_time"] == "120000"
    with pytest.raises(ValueError, match="WGS84"):
        geojson_feature(update, reference_frame="other")  # type: ignore[arg-type]


def test_ros_adapter_requires_explicit_augmented_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NavSatFix:
        COVARIANCE_TYPE_UNKNOWN = 0

        def __init__(self) -> None:
            self.header = SimpleNamespace()
            self.status = SimpleNamespace()

    monkeypatch.setattr(
        "um982py.adapters.import_module", lambda _: SimpleNamespace(NavSatFix=NavSatFix)
    )
    stamp = object()
    message = navsatfix(fix(), stamp=stamp, frame_id="antenna", reference_frame="WGS84")
    assert message.header.stamp is stamp and message.header.frame_id == "antenna"
    assert message.status.status == 0 and message.status.service == 0
    assert (message.latitude, message.longitude, message.altitude) == (50, 8, 145)
    assert message.position_covariance_type == 0
    unknown = navsatfix(
        fix(4), stamp=stamp, frame_id="antenna", reference_frame="WGS84"
    )
    assert unknown.status.status == -1 and isnan(unknown.latitude)
    augmented = navsatfix(
        fix(4), stamp=stamp, frame_id="antenna", reference_frame="WGS84", status=2
    )
    assert augmented.status.status == 2 and augmented.latitude == 50
    with pytest.raises(ValueError, match="valid position"):
        navsatfix(
            fix(0), stamp=stamp, frame_id="antenna", reference_frame="WGS84", status=2
        )


def test_ros_bestnav_covariance_uses_east_north_up_variances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NavSatFix:
        COVARIANCE_TYPE_UNKNOWN = 0
        COVARIANCE_TYPE_DIAGONAL_KNOWN = 2

        def __init__(self) -> None:
            self.header = SimpleNamespace()
            self.status = SimpleNamespace()
            self.position_covariance = [0.0] * 9

    monkeypatch.setattr(
        "um982py.adapters.import_module", lambda _: SimpleNamespace(NavSatFix=NavSatFix)
    )
    position = replace(
        BestNavigation.from_record(decode_log(manual_message("BESTNAVA"))),
        solution_status=SolutionStatus.SOL_COMPUTED,
        position_type=PositionType.SINGLE,
        datum="WGS84",
        latitude_std_m=2.0,
        longitude_std_m=3.0,
        height_std_m=4.0,
    )
    kwargs = {"stamp": object(), "frame_id": "antenna", "reference_frame": "WGS84"}
    message = navsatfix(position, **kwargs)
    assert message.status.status == 0
    assert message.position_covariance_type == 2
    assert message.position_covariance == [9, 0, 0, 0, 4, 0, 0, 0, 16]
    assert message.altitude == position.ellipsoidal_height

    incomplete = navsatfix(replace(position, height_std_m=None), **kwargs)
    assert incomplete.position_covariance_type == 0
    augmented = replace(position, position_type=PositionType.NARROW_INT)
    assert navsatfix(augmented, **kwargs).status.status == -1
    assert navsatfix(augmented, status=2, **kwargs).position_covariance_type == 2
    invalid = replace(position, solution_status=SolutionStatus.INSUFFICIENT_OBS)
    assert navsatfix(invalid, **kwargs).position_covariance_type == 0
    with pytest.raises(ValueError, match="valid position"):
        navsatfix(invalid, status=2, **kwargs)
    with pytest.raises(ValueError, match="datum"):
        navsatfix(replace(position, datum=0), **kwargs)
    with pytest.raises(ValueError, match="covariance"):
        navsatfix(replace(position, latitude_std_m=1e300), **kwargs)
