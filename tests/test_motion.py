from dataclasses import replace

import pytest

from test_bodies import manual_message
from um982py import Motion, RoverPosition
from um982py.messages import BestNavigation, decode_log
from um982py.messages.enums import PositionType, SolutionStatus


def navigation() -> BestNavigation:
    return replace(
        BestNavigation.from_record(decode_log(manual_message("BESTNAVA"))),
        solution_status=SolutionStatus.SOL_COMPUTED,
        position_type=PositionType.SINGLE,
        velocity_solution_status=SolutionStatus.SOL_COMPUTED,
        velocity_type=PositionType.SINGLE,
        latitude=0,
        longitude=0,
        horizontal_speed=10,
        track=90,
        vertical_speed=-2,
        epoch_gps_seconds=1000,
        velocity_latency_s=0.25,
    )


def test_rover_motion_separates_heading_and_course_for_waypoint() -> None:
    nav = navigation()
    rover = RoverPosition(nav, 350, 2, 0.1, PositionType.NARROW_INT, 1)
    motion = rover.motion(heading_offset_deg=20)
    assert motion.ground_speed_m_s == 10
    assert motion.course_deg == 90
    assert motion.heading_deg == 10
    assert motion.vertical_speed_m_s == -2
    assert motion.velocity_epoch_gps_seconds == 999.75
    destination = motion.waypoint(0, 1)
    assert destination.bearing_deg == pytest.approx(90)
    assert destination.turn_deg == pytest.approx(80)
    assert destination.closing_speed_m_s == pytest.approx(10)
    assert destination.distance_m == pytest.approx(111_195, abs=2)
    assert motion.waypoint(0, -1).closing_speed_m_s == pytest.approx(-10)
    assert motion.waypoint(0, 0).closing_speed_m_s is None


def test_motion_suppresses_invalid_velocity_and_low_speed_course() -> None:
    nav = navigation()
    slow = replace(nav, horizontal_speed=0.1).motion()
    assert slow.ground_speed_m_s == 0.1 and slow.course_deg is None
    assert slow.waypoint(0, 1).closing_speed_m_s is None
    assert (
        replace(nav, horizontal_speed=0).motion(min_course_speed_m_s=0).course_deg
        is None
    )
    assert replace(nav, track=361).motion().course_deg is None
    assert replace(nav, horizontal_speed=-1).motion().ground_speed_m_s is None
    missing = replace(nav, velocity_solution_status=SolutionStatus.INSUFFICIENT_OBS)
    assert missing.motion().ground_speed_m_s is None
    assert missing.motion().vertical_speed_m_s is None
    assert missing.motion().velocity_epoch_gps_seconds is None
    assert (
        replace(nav, velocity_latency_s=None).motion().velocity_epoch_gps_seconds
        is None
    )
    invalid = replace(nav, solution_status=SolutionStatus.INSUFFICIENT_OBS)
    motion = Motion.from_navigation(invalid, heading_deg=30)
    assert motion.heading_deg is None and motion.course_deg is None
    with pytest.raises(ValueError, match="valid position"):
        motion.waypoint(0, 1)


def test_motion_validates_user_settings() -> None:
    nav = navigation()
    with pytest.raises(ValueError, match="heading offset"):
        Motion.from_navigation(nav, heading_offset_deg=float("nan"))
    with pytest.raises(ValueError, match="heading must"):
        Motion.from_navigation(nav, heading_deg=-1)
    with pytest.raises(ValueError, match="minimum course"):
        nav.motion(min_course_speed_m_s=-1)


def test_bestnav_decodes_receiver_velocity_latency() -> None:
    record = decode_log(manual_message("BESTNAVA"))
    position = BestNavigation.from_record(record)
    assert position.velocity_latency_s == pytest.approx(record.real("latency"))


@pytest.mark.parametrize("latency", [-1.0, float("nan")])
def test_invalid_receiver_velocity_latency_is_unavailable(latency: float) -> None:
    record = decode_log(manual_message("BESTNAVA"))
    entries = tuple(
        (name, latency if name == "latency" else value)
        for name, value in record.entries
    )
    position = BestNavigation.from_record(replace(record, entries=entries))
    assert position.valid
    assert position.velocity_latency_s is None
