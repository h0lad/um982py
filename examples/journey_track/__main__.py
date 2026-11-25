# Capture a journey with Doppler-derived ground speed, course and vertical motion.

import math
from collections.abc import Sequence
from dataclasses import dataclass

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.heading_attitude import attitude_from_record, swapped_attitude
from um982py.commands import Log
from um982py.field_data import file_sha256, nearest_epoch
from um982py.geodesy import enu_from_ecef, geodetic_from_ecef
from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.motion import waypoint_direction

_COMPUTED = (0, "SOL_COMPUTED")
_DOPPLER_VELOCITY = (8, "DOPPLER_VELOCITY")


@dataclass(frozen=True, slots=True)
class _DopplerSample:
    epoch: float
    status: object
    velocity_type: object
    ground_speed_mps: float
    course_true_deg: float | None
    vertical_speed_mps: float | None
    latency_s: float | None
    age_s: float | None
    ground_speed_std_mps: float | None
    vertical_speed_std_mps: float | None


def _finite(record: Record, key: str) -> float | None:
    try:
        value = record.real(key)
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _positive_finite(record: Record, key: str) -> float | None:
    value = _finite(record, key)
    return value if value is not None and value >= 0 else None


def _is_doppler(record: Record) -> bool:
    return record.name.upper().startswith("DOPPVEL")


def _doppler_samples(
    records: Sequence[Record],
) -> tuple[list[_DopplerSample], int]:
    """Keep computed DOPPVEL reports with finite ground speed."""
    samples: list[_DopplerSample] = []
    rejected = 0
    for row in records:
        if row.get("v_sol_status") not in _COMPUTED or (
            "vel_type" in row and row["vel_type"] not in _DOPPLER_VELOCITY
        ):
            rejected += 1
            continue
        try:
            epoch = gps_epoch(row)
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        speed = _finite(row, "hor_spd")
        if not math.isfinite(epoch) or speed is None or speed < 0:
            rejected += 1
            continue
        track = _finite(row, "trk_gnd")
        samples.append(
            _DopplerSample(
                epoch=epoch,
                status=row["v_sol_status"],
                velocity_type=row.get("vel_type"),
                ground_speed_mps=speed,
                course_true_deg=track % 360 if track is not None else None,
                vertical_speed_mps=_finite(row, "vert_spd"),
                latency_s=_finite(row, "latency"),
                age_s=_finite(row, "age"),
                ground_speed_std_mps=_positive_finite(row, "horspd_std"),
                vertical_speed_std_mps=_positive_finite(row, "verspd_std"),
            )
        )
    samples.sort(key=lambda sample: sample.epoch)
    return samples, rejected


def _legacy_doppler_velocity(
    record: Record, latitude: float, longitude: float
) -> tuple[float, float | None, float, float | None] | None:
    """Read a Doppler-typed ECEF velocity from an older BESTNAVXYZ capture."""
    if (
        record.get("v_sol_status") not in _COMPUTED
        or record.get("vel_type") not in _DOPPLER_VELOCITY
    ):
        return None
    xyz = tuple(record.real(key) for key in ("v_x", "v_y", "v_z"))
    if not all(math.isfinite(value) for value in xyz):
        return None
    east, north, up = enu_from_ecef(xyz[0], xyz[1], xyz[2], latitude, longitude)
    speed = math.hypot(east, north)
    course = math.degrees(math.atan2(east, north)) % 360 if speed > 0 else None
    return speed, course, up, _finite(record, "v_latency")


def _nearest_doppler(
    samples: Sequence[tuple[float, _DopplerSample]],
    times: Sequence[float],
    epoch: float,
    tolerance: float,
) -> _DopplerSample | None:
    nearest = nearest_epoch(samples, times, epoch)
    if nearest is None or abs(nearest[0] - epoch) > tolerance:
        return None
    return nearest[1]


def analyze(
    positions: Sequence[Record],
    *groups: Sequence[Record],
    doppler: Sequence[Record] | None = None,
    baselines: Sequence[Record] | None = None,
    max_gap: float,
    moving_threshold: float,
    course_threshold: float,
    heading_tolerance: float,
    doppler_tolerance: float = 0.5,
    doppler_tolerance_s: float | None = None,
    swapped: bool,
    waypoint: tuple[float, float] | None = None,
) -> dict[str, object]:
    """Pair positions with Doppler velocity reports and summarize motion.

    ``groups`` accepts DOPPVEL and baseline record sequences in either order so
    older calls that pass baselines as the second argument keep working.
    ``doppler_tolerance_s`` mirrors the command-line option name.
    """
    if doppler_tolerance_s is not None:
        doppler_tolerance = doppler_tolerance_s
    doppler_records = list(doppler or ())
    baseline_records = list(baselines or ())
    for group in groups:
        for record in group:
            if _is_doppler(record):
                doppler_records.append(record)
            else:
                baseline_records.append(record)
    allow_legacy_velocity = not doppler_records
    doppler_samples, rejected_doppler = _doppler_samples(doppler_records)
    doppler_pairs = [(sample.epoch, sample) for sample in doppler_samples]
    doppler_times = [sample.epoch for sample in doppler_samples]

    headings = []
    for record in baseline_records:
        if record.get("p_sol_status") not in _COMPUTED:
            continue
        try:
            attitude = attitude_from_record(record)
            if swapped:
                attitude = swapped_attitude(attitude)
            if not math.isfinite(attitude.heading):
                continue
            headings.append((gps_epoch(record), attitude.heading))
        except (KeyError, TypeError, ValueError):
            continue

    samples: list[dict[str, object]] = []
    previous: tuple[float, float] | None = None
    last_epoch: float | None = None
    distance = moving = covered = 0.0
    gaps = rejected = matched_doppler = 0
    speeds: list[float] = []
    matched_samples: set[_DopplerSample] = set()
    sources: set[str] = set()
    for row in positions:
        epoch = gps_epoch(row)
        if last_epoch is not None and epoch <= last_epoch:
            raise ValueError("BESTNAVXYZ epochs must be strictly increasing")
        last_epoch = epoch
        if row["p_sol_status"] not in _COMPUTED:
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

        velocity_source = None
        velocity_status = velocity_type = None
        velocity_epoch_offset = velocity_latency = velocity_age = None
        speed_std = vertical_std = None
        speed: float | None
        course: float | None
        vertical: float | None
        doppler_sample = _nearest_doppler(
            doppler_pairs, doppler_times, epoch, doppler_tolerance
        )
        if doppler_sample is not None:
            velocity_source = "DOPPVEL"
            velocity_status = doppler_sample.status
            velocity_type = doppler_sample.velocity_type
            speed = doppler_sample.ground_speed_mps
            vertical = doppler_sample.vertical_speed_mps
            course = (
                doppler_sample.course_true_deg
                if doppler_sample.course_true_deg is not None
                and speed >= course_threshold
                else None
            )
            velocity_epoch_offset = doppler_sample.epoch - epoch
            velocity_latency = doppler_sample.latency_s
            velocity_age = doppler_sample.age_s
            speed_std = doppler_sample.ground_speed_std_mps
            vertical_std = doppler_sample.vertical_speed_std_mps
            matched_doppler += 1
            matched_samples.add(doppler_sample)
        else:
            legacy = (
                _legacy_doppler_velocity(row, latitude, longitude)
                if allow_legacy_velocity
                else None
            )
            if legacy is not None:
                velocity_source = "BESTNAVXYZ_DOPPLER"
                velocity_status = row["v_sol_status"]
                velocity_type = row["vel_type"]
                speed, course, vertical, velocity_latency = legacy
                if course is not None and speed < course_threshold:
                    course = None
            else:
                speed = course = vertical = None
        if speed is not None:
            speeds.append(speed)
            sources.add(velocity_source or "unknown")
        if speed is not None and previous is not None:
            dt = epoch - previous[0]
            if dt <= max_gap:
                covered += dt
                distance += (previous[1] + speed) * dt / 2
                if (previous[1] + speed) / 2 >= moving_threshold:
                    moving += dt
            else:
                gaps += 1
        previous = (epoch, speed) if speed is not None else None
        nearest_heading = min(
            headings, key=lambda item: abs(item[0] - epoch), default=None
        )
        matched_heading = (
            nearest_heading
            if nearest_heading and abs(nearest_heading[0] - epoch) <= heading_tolerance
            else None
        )
        direction = (
            waypoint_direction(latitude, longitude, *waypoint) if waypoint else None
        )
        waypoint_distance = direction.distance_m if direction else None
        waypoint_bearing = direction.bearing_deg if direction else None
        waypoint_vmg = (
            speed * math.cos(math.radians(waypoint_bearing - course))
            if speed is not None and course is not None and waypoint_bearing is not None
            else None
        )
        samples.append(
            {
                "gps_seconds": epoch,
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "ellipsoidal_height_m": height,
                "position_ecef_standard_deviation_m": [
                    row.real(name) if name in row else None
                    for name in ("p_x_std", "p_y_std", "p_z_std")
                ],
                "position_type": row["pos_type"],
                "velocity_source": velocity_source,
                "velocity_status": velocity_status,
                "velocity_type": velocity_type,
                "velocity_epoch_offset_s": velocity_epoch_offset,
                "doppler_epoch_offset_s": velocity_epoch_offset,
                "velocity_latency_s": velocity_latency,
                "velocity_age_s": velocity_age,
                "ground_speed_mps": speed,
                "ground_speed_standard_deviation_mps": speed_std,
                "ground_speed_knots": speed * 3600 / 1852
                if speed is not None
                else None,
                "ground_speed_kmh": speed * 3.6 if speed is not None else None,
                "course_true_deg": course,
                "vertical_speed_mps": vertical,
                "vertical_speed_standard_deviation_mps": vertical_std,
                "vertical_speed_ft_per_min": vertical * 60 / 0.3048
                if vertical is not None
                else None,
                "waypoint_distance_spherical_m": waypoint_distance,
                "waypoint_bearing_true_deg": waypoint_bearing,
                "waypoint_closing_speed_mps": waypoint_vmg,
                "baseline_heading_true_deg": matched_heading[1]
                if matched_heading
                else None,
                "heading_epoch_offset_s": matched_heading[0] - epoch
                if matched_heading
                else None,
            }
        )
    return {
        "status": "ok" if samples else "no_computed_position",
        "velocity_sources": sorted(sources),
        "matched_doppler_epochs": matched_doppler,
        "unmatched_doppler_epochs": len(doppler_samples) - len(matched_samples),
        "rejected_doppler_epochs": rejected_doppler,
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
    parser.add_output_interval(default=1)
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
        "--doppler-tolerance-s",
        type=float,
        default=0.5,
        help="maximum offset between a position and its Doppler velocity epoch",
    )
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
            not math.isfinite(value) or value < 0
            for value in (
                args.moving_threshold_mps,
                args.course_threshold_mps,
                args.heading_tolerance_s,
                args.doppler_tolerance_s,
            )
        )
        or not math.isfinite(args.max_gap_s)
        or args.max_gap_s <= 0
    ):
        parser.error(
            "thresholds must be finite and non-negative; maximum gap must be positive"
        )
    paths = [path for path in (args.replay, args.record, args.json) if path is not None]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("replay, recording and report paths must be distinct")
    if args.waypoint is not None and (
        not all(math.isfinite(value) for value in args.waypoint)
        or not -90 <= args.waypoint[0] <= 90
        or not -180 <= args.waypoint[1] <= 180
    ):
        parser.error("waypoint latitude and longitude must be finite and in range")
    logs: list[Log] = [Log.BESTNAVXYZ, Log.DOPPVEL]
    if args.dual_heading:
        logs.append(Log.BSLNENUHD)
    captured = capture_records(
        args, logs, duration=args.duration, interval=args.interval
    )
    report = analyze(
        captured["BESTNAVXYZ"],
        doppler=captured["DOPPVEL"],
        baselines=captured.get("BSLNENUHD", ()),
        max_gap=args.max_gap_s,
        moving_threshold=args.moving_threshold_mps,
        course_threshold=args.course_threshold_mps,
        heading_tolerance=args.heading_tolerance_s,
        doppler_tolerance=args.doppler_tolerance_s,
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
                "doppler_tolerance_s": args.doppler_tolerance_s,
                "waypoint_lat_lon": args.waypoint,
            },
            "replay_sha256": file_sha256(args.replay) if args.replay else None,
            "limitations": (
                "Ground speed and course come from the computed DOPPVEL Doppler "
                "solution when a report pairs with the position epoch. Captures "
                "with no DOPPVEL records fall back to Doppler-typed ECEF velocity. "
                "Course over ground is not antenna or vehicle heading. Ellipsoidal "
                "height is not pressure altitude or terrain clearance. Baseline "
                "heading requires a known antenna orientation and is not "
                "automatically vehicle heading. Integration omits gaps and can "
                "accumulate velocity error. Doppler epochs, receiver latency and "
                "reported standard deviations are not corrected or propagated. "
                "The receiver and position solution share observations, so "
                "agreement is not independent accuracy."
            ),
        }
    )
    write_json(report, args.json)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
