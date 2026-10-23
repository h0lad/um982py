"""Capture a journey with GNSS ground speed, course and vertical motion."""

import math
from collections.abc import Sequence

from examples.heading_attitude import attitude_from_record, swapped_attitude
from um982py.capture import capture_records, record_epoch
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.field_data import file_sha256
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef
from um982py.messages import Record


def waypoint_geometry(
    latitude: float, longitude: float, target: tuple[float, float]
) -> tuple[float, float | None]:
    """Approximate great-circle distance and initial bearing on a mean Earth sphere."""
    phi1, phi2 = math.radians(latitude), math.radians(target[0])
    delta_lon = math.radians(target[1] - longitude)
    y = math.sin(delta_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        delta_lon
    )
    central = math.atan2(
        math.hypot(x, y),
        math.sin(phi1) * math.sin(phi2)
        + math.cos(phi1) * math.cos(phi2) * math.cos(delta_lon),
    )
    bearing = math.degrees(math.atan2(y, x)) % 360 if math.hypot(x, y) > 1e-12 else None
    return 6371008.8 * central, bearing


def analyze(
    positions: Sequence[Record],
    baselines: Sequence[Record],
    *,
    max_gap: float,
    moving_threshold: float,
    course_threshold: float,
    heading_tolerance: float,
    swapped: bool,
    waypoint: tuple[float, float] | None = None,
) -> dict[str, object]:
    """Analyze ordered solutions without bridging missing or invalid epochs."""
    headings = []
    for record in baselines:
        if record["p_sol_status"] not in (0, "SOL_COMPUTED"):
            continue
        try:
            attitude = attitude_from_record(record)
            if swapped:
                attitude = swapped_attitude(attitude)
            if not math.isfinite(attitude.heading):
                continue
            headings.append((record_epoch(record), attitude.heading))
        except ValueError:
            continue
    samples: list[dict[str, object]] = []
    previous: tuple[float, float] | None = None
    last_epoch: float | None = None
    distance = moving = covered = 0.0
    gaps = rejected = 0
    speeds = []
    for row in positions:
        epoch = record_epoch(row)
        if last_epoch is not None and epoch <= last_epoch:
            raise ValueError("BESTNAVXYZ epochs must be strictly increasing")
        last_epoch = epoch
        if row["p_sol_status"] not in (0, "SOL_COMPUTED"):
            rejected += 1
            previous = None
            continue
        try:
            latitude, longitude, height = geodetic_from_ecef(
                row.real("p_x"), row.real("p_y"), row.real("p_z")
            )
        except (ValueError, ZeroDivisionError):
            rejected += 1
            previous = None
            continue
        velocity = None
        speed = course = vertical = None
        if row["v_sol_status"] in (0, "SOL_COMPUTED"):
            xyz = tuple(row.real(key) for key in ("v_x", "v_y", "v_z"))
            if all(math.isfinite(value) for value in xyz):
                velocity = enu_from_ecef(xyz[0], xyz[1], xyz[2], latitude, longitude)
                speed = math.hypot(velocity[0], velocity[1])
                vertical = velocity[2]
                speeds.append(speed)
                if speed >= course_threshold and speed > 0:
                    course = math.degrees(math.atan2(velocity[0], velocity[1])) % 360
        if speed is not None and previous is not None:
            dt = epoch - previous[0]
            if dt <= max_gap:
                covered += dt
                distance += (previous[1] + speed) * dt / 2
                # Classify each interval using its mean speed.
                if (previous[1] + speed) / 2 >= moving_threshold:
                    moving += dt
            else:
                gaps += 1
        previous = (epoch, speed) if speed is not None else None
        nearest = min(headings, key=lambda item: abs(item[0] - epoch), default=None)
        matched = (
            nearest
            if nearest and abs(nearest[0] - epoch) <= heading_tolerance
            else None
        )
        waypoint_distance, waypoint_bearing = (
            waypoint_geometry(latitude, longitude, waypoint)
            if waypoint is not None
            else (None, None)
        )
        waypoint_vmg = (
            velocity[0] * math.sin(math.radians(waypoint_bearing))
            + velocity[1] * math.cos(math.radians(waypoint_bearing))
            if velocity is not None and waypoint_bearing is not None
            else None
        )
        samples.append(
            {
                "gps_seconds": epoch,
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "ellipsoidal_height_m": height,
                "position_type": row["pos_type"],
                "velocity_status": row["v_sol_status"],
                "velocity_type": row["vel_type"],
                "velocity_latency_s": row.real("v_latency"),
                "ground_speed_mps": speed,
                "ground_speed_knots": speed * 3600 / 1852
                if speed is not None
                else None,
                "ground_speed_kmh": speed * 3.6 if speed is not None else None,
                "course_true_deg": course,
                "vertical_speed_mps": vertical,
                "vertical_speed_ft_per_min": vertical * 60 / 0.3048
                if vertical is not None
                else None,
                "waypoint_distance_spherical_m": waypoint_distance,
                "waypoint_bearing_true_deg": waypoint_bearing,
                "waypoint_closing_speed_mps": waypoint_vmg,
                "baseline_heading_true_deg": matched[1] if matched else None,
                "heading_epoch_offset_s": matched[0] - epoch if matched else None,
            }
        )
    return {
        "status": "ok" if samples else "no_computed_position",
        "samples": samples,
        "integrated_ground_distance_m": distance if covered else None,
        "covered_velocity_interval_s": covered,
        "moving_time_s": moving if covered else None,
        "maximum_sample_ground_speed_mps": max(speeds, default=None),
        "gaps_over_limit": gaps,
        "rejected_position_epochs": rejected,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument(
        "--profile", choices=("marine", "aviation", "sport"), required=True
    )
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--max-gap-s", type=float, default=2)
    parser.add_argument("--moving-threshold-mps", type=float, default=0.5)
    parser.add_argument("--course-threshold-mps", type=float, default=1)
    parser.add_argument(
        "--dual-heading",
        action="store_true",
        help="also capture the dual-antenna baseline",
    )
    parser.add_argument("--heading-tolerance-s", type=float, default=0.5)
    parser.add_argument(
        "--waypoint",
        type=float,
        nargs=2,
        metavar=("LAT", "LON"),
        help="optional destination in decimal degrees",
    )
    args = parser.parse_args(argv)
    if (
        any(
            not math.isfinite(v) or v < 0
            for v in (
                args.moving_threshold_mps,
                args.course_threshold_mps,
                args.heading_tolerance_s,
            )
        )
        or not math.isfinite(args.max_gap_s)
        or args.max_gap_s <= 0
    ):
        parser.error(
            "thresholds must be finite and non-negative; maximum gap must be positive"
        )
    paths = [p for p in (args.replay, args.record, args.json) if p is not None]
    if len({p.resolve() for p in paths}) != len(paths):
        parser.error("replay, recording and report paths must be distinct")
    if args.waypoint is not None and (
        not all(math.isfinite(v) for v in args.waypoint)
        or not -90 <= args.waypoint[0] <= 90
        or not -180 <= args.waypoint[1] <= 180
    ):
        parser.error("waypoint latitude and longitude must be finite and in range")
    logs: list[Log | FirmwareLog] = [Log.BESTNAVXYZ]
    if args.dual_heading:
        logs.append(FirmwareLog.BSLNENUHD)
    captured = capture_records(
        args, logs, duration=args.duration, interval=args.interval
    )
    report = analyze(
        captured["BESTNAVXYZ"],
        captured.get("BSLNENUHD", ()),
        max_gap=args.max_gap_s,
        moving_threshold=args.moving_threshold_mps,
        course_threshold=args.course_threshold_mps,
        heading_tolerance=args.heading_tolerance_s,
        swapped=args.swap_antennas,
        waypoint=tuple(args.waypoint) if args.waypoint is not None else None,
    )
    report.update(
        {
            "profile": args.profile,
            "parameters": {
                "max_gap_s": args.max_gap_s,
                "moving_threshold_mps": args.moving_threshold_mps,
                "course_threshold_mps": args.course_threshold_mps,
                "heading_tolerance_s": args.heading_tolerance_s,
                "waypoint_lat_lon": args.waypoint,
            },
            "replay_sha256": file_sha256(args.replay) if args.replay else None,
            "limitations": (
                "GNSS speed and course are over ground, not through water or air. "
                "Ellipsoidal height is not pressure altitude or terrain clearance. "
                "Baseline heading requires a known antenna orientation and is not "
                "automatically vehicle heading. Integration omits gaps and can "
                "accumulate velocity error. This is an experimental log, not a "
                "certified navigation or safety system."
            ),
        }
    )
    write_json(report, args.json)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
