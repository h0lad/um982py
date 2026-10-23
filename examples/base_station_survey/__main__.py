"""Capture a BESTXYZ track and report the survey-in average."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence

from examples.base_station_survey import (
    AxisStatistics,
    SurveyCriteria,
    SurveyResult,
    SurveySample,
    survey,
)
from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.corrections import stale_correction
from um982py.experimental import FirmwareLog
from um982py.geodesy import haversine_distance
from um982py.messages.record import Record


def sample_from_record(record: Record) -> SurveySample:
    """Turn one ``BESTXYZ`` record into a sample weighted by inverse variance."""
    deviation = (
        math.fsum(record.real(key) ** 2 for key in ("p_x_std", "p_y_std", "p_z_std"))
        / 3.0
    )
    weight = 1.0 / deviation if deviation > 0 else 1.0
    return SurveySample(
        x=record.real("p_x"),
        y=record.real("p_y"),
        z=record.real("p_z"),
        weight=weight,
    )


def axis_payload(axis: AxisStatistics) -> dict[str, float]:
    """Serialisable view of one axis."""
    return {
        "mean": axis.mean,
        "std": axis.std,
        "standard_error": axis.standard_error,
    }


def payload_of(
    result: SurveyResult, crosscheck: dict[str, object] | None
) -> dict[str, object]:
    """Serialisable view of a survey result."""
    return {
        "status": "ok" if result.converged else "not_converged",
        "count": result.count,
        "total_weight": result.total_weight,
        "ecef": list(result.ecef),
        "latitude": result.latitude,
        "longitude": result.longitude,
        "height": result.height,
        "horizontal_standard_error": result.horizontal_standard_error,
        "converged": result.converged,
        "x": axis_payload(result.x),
        "y": axis_payload(result.y),
        "z": axis_payload(result.z),
        "east": axis_payload(result.east),
        "north": axis_payload(result.north),
        "up": axis_payload(result.up),
        "vertical_standard_error": result.up.standard_error,
        "bestnav_crosscheck": crosscheck,
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.base_station_survey",
        description="BESTXYZ survey-in averaging",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument("--minimum-samples", type=int, default=30)
    parser.add_argument("--horizontal-tolerance", type=float, default=0.05)
    parser.add_argument("--vertical-tolerance", type=float, default=0.10)
    parser.add_argument(
        "--frames", type=int, default=120, help="BESTXYZ epochs to collect"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(
            f"base_station_survey debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def _bestnav_crosscheck(
    records: tuple[Record, ...], result: SurveyResult
) -> dict[str, object] | None:
    """Compare the survey mean with the latest computed BESTNAV fix."""
    fixes = tuple(
        record
        for record in records
        if record.get("p_sol_status") in (0, "SOL_COMPUTED")
    )
    if not fixes:
        return None
    latest = fixes[-1]
    try:
        latitude = latest.real("lat")
        longitude = latest.real("lon")
        height = latest.real("hgt")
    except (KeyError, TypeError, ValueError):
        return None
    undulation = latest.get("undulation")
    if not isinstance(undulation, (int, float)):
        undulation = None
    horizontal_offset = haversine_distance(
        latitude, longitude, result.latitude, result.longitude
    )
    ellipsoid = height + undulation if undulation is not None else None
    height_offset = result.height - ellipsoid if ellipsoid is not None else None
    warn = height_offset is not None and abs(height_offset) > 2.0
    return {
        "horizontal_offset_m": horizontal_offset,
        "height_offset_m": height_offset,
        "undulation_m": undulation,
        "bestnav_ellipsoid_m": ellipsoid,
        "height_warn": warn,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Survey the positions reported by consecutive ``BESTXYZ`` frames."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"base_station_survey debug: {origin}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    captured = capture_records(
        args,
        [FirmwareLog.BESTXYZ, Log.BESTNAV],
        duration=args.duration,
        frames=args.frames,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    records = captured["BESTXYZ"]
    records = tuple(
        record
        for record in records
        if record.get("p_sol_status") in (0, "SOL_COMPUTED")
    )
    if not records:
        parser.error("capture contains no computed BESTXYZ positions")
    fresh = tuple(
        record
        for record in records
        if not stale_correction(record.get("pos_type"), record.get("diff_age"))
    )
    if len(fresh) != len(records):
        print(
            f"Skipped {len(records) - len(fresh)} positions with stale corrections",
            file=sys.stderr,
        )
    if not fresh:
        write_json(
            {
                "status": "insufficient_data",
                "sample_count": len(records),
                "reason": "no BESTXYZ positions with fresh corrections",
            },
            args.json,
        )
        return 1
    result = survey(
        [sample_from_record(record) for record in fresh],
        SurveyCriteria(
            minimum_samples=args.minimum_samples,
            horizontal_tolerance=args.horizontal_tolerance,
            vertical_tolerance=args.vertical_tolerance,
        ),
    )
    x, y, z = result.ecef
    crosscheck = _bestnav_crosscheck(captured.get("BESTNAV", ()), result)
    offset = crosscheck["height_offset_m"] if crosscheck is not None else None
    if (
        crosscheck is not None
        and crosscheck["height_warn"]
        and isinstance(offset, float)
    ):
        print(
            f"warning: survey ellipsoid height disagrees with BESTNAV by "
            f"{offset:.2f} m; check the antenna setup before using the "
            "survey height",
            file=sys.stderr,
        )
    print(
        f"Survey: {result.count} samples; converged {result.converged}; "
        f"ecef {x:.4f} {y:.4f} {z:.4f}; "
        f"geodetic {result.latitude:.9f} {result.longitude:.9f} "
        f"{result.height:.4f} m; "
        f"horizontal standard error {result.horizontal_standard_error:.4f} m",
        file=sys.stderr,
    )
    print(f"samples {result.count} converged {result.converged}")
    print(f"ecef {x:.4f} {y:.4f} {z:.4f}")
    print(f"geodetic {result.latitude:.9f} {result.longitude:.9f} {result.height:.4f}")
    print(f"horizontal standard error {result.horizontal_standard_error:.4f} m")
    write_json(payload_of(result, crosscheck), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
