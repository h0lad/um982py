"""Capture a position track and write JSON, CSV or GeoJSON."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from examples.position_tracking import (
    Geofence,
    TrackPoint,
    analyze_capture,
    collect_positions,
    select_track,
    write_positions_csv,
)
from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.messages.record import Record


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.position_tracking",
        description="Collect positions, receiver precision and satellite signals",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="position log interval in seconds"
    )
    parser.add_argument(
        "--precision-service",
        dest="ppp_service",
        choices=("AUTO", "E6-HAS", "B2B-PPP"),
        help="select a live PPP provider, using PPPNAV automatically when ready",
    )
    parser.add_argument(
        "--geofence",
        type=float,
        nargs=3,
        metavar=("LAT", "LON", "RADIUS"),
        help="report fixes outside this circle, radius in metres",
    )
    parser.add_argument("--geojson", type=Path, help="write the track as GeoJSON")
    parser.add_argument("--csv", type=Path, help="write one position per CSV row")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live position and quality updates to stderr",
    )
    return parser


def _fence(values: list[float] | None) -> Geofence | None:
    if values is None:
        return None
    latitude, longitude, radius = values
    if not all(math.isfinite(value) for value in values):
        raise ValueError("geofence coordinates and radius must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("geofence latitude or longitude is out of range")
    return Geofence(latitude, longitude, radius)


def _precision_line(point: TrackPoint) -> str:
    parts = [f"tracked={point.satellites}"]
    if point.solution_satellites is not None:
        parts.append(f"used={point.solution_satellites}")
    if point.horizontal_sigma_m is not None:
        parts.append(f"horizontal_sigma={point.horizontal_sigma_m:.3f} m")
    if point.height_sigma_m is not None:
        parts.append(f"height_sigma={point.height_sigma_m:.3f} m")
    if point.correction_age_s is not None:
        parts.append(f"correction_age={point.correction_age_s:.1f} s")
    return ", ".join(parts)


def _progress_callback(
    interval_s: float,
) -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}
    previous_source: str | None = None

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        nonlocal previous_source
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        best, _ = collect_positions(captured.get("BESTNAV", ()))
        ppp, _ = collect_positions(captured.get("PPPNAV", ()), ppp=True)
        track, _ = select_track(best, ppp, interval_s=interval_s)
        message = f"records={counts}; fixes={len(track.points)}"
        if track.points:
            latest = track.points[-1]
            message += (
                f"; {latest.source} {latest.position_type}; "
                f"{latest.latitude:.9f}, {latest.longitude:.9f}, "
                f"{latest.altitude:.3f} m; {_precision_line(latest)}"
            )
            if previous_source is not None and latest.source != previous_source:
                message += f"; source changed to {latest.source}"
            previous_source = latest.source
        print(f"position_tracking debug: {message}", file=sys.stderr, flush=True)

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    fence = _fence(args.geofence)
    primary = args.antenna in ("primary", "1") and not args.swap_antennas
    logs = [Log.BESTNAV, Log.STADOP, Log.SATSINFO]
    if primary or args.ppp_service is not None:
        logs.append(Log.PPPNAV)
    if primary:
        logs.append(Log.PPPDOP)
    if args.debug:
        mode = (
            f"PPP {args.ppp_service}"
            if args.ppp_service is not None
            else "automatic BESTNAV/PPP"
        )
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"position_tracking debug: {origin}; mode={mode}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    captured = capture_records(
        args,
        logs,
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback(args.interval) if args.debug else None,
    )
    result = analyze_capture(
        captured,
        interval_s=args.interval,
        precision_service=args.ppp_service,
        fence=fence,
    )
    latest = result.track.points[-1] if result.track.points else None
    print(
        f"Position track: {result.status}; {len(result.track.points)} accepted of "
        f"{sum(len(captured.get(name, ())) for name in ('BESTNAV', 'PPPNAV'))} "
        "navigation records; "
        + (
            f"latest {latest.latitude:.9f}, {latest.longitude:.9f}, "
            f"{latest.altitude:.3f} m ({latest.position_type}); "
            f"{_precision_line(latest)}"
            if latest is not None
            else "no computed position"
        ),
        file=sys.stderr,
    )
    if args.debug:
        print(
            f"position_tracking debug: rejected={result.report['rejected']}",
            file=sys.stderr,
        )
    if args.geojson is not None:
        write_json(result.track.geojson(), args.geojson)
    if args.csv is not None:
        write_positions_csv(result.track, args.csv)
    write_json(result.report, args.json)
    if args.debug:
        print(
            f"position_tracking debug: JSON={args.json or 'stdout'}; "
            f"CSV={args.csv}; GeoJSON={args.geojson}",
            file=sys.stderr,
        )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run(main))
