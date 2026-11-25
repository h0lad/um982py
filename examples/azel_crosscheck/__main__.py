# Compare broadcast-orbit azimuth and elevation with SATVIS2.

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records, selected_log
from examples.azel_crosscheck import (
    DIRECTION_TOLERANCE_DEGREES,
    CrossCheckReport,
    cross_check,
    native_number,
)
from um982py.capture import decode_records, read_frames, select_position_pair
from um982py.commands import Log
from um982py.geodesy import receiver_ecef
from um982py.gnss import WEEK_SECONDS
from um982py.measurement import gps_epoch
from um982py.messages import (
    Record,
)
from um982py.messages.enums import SatelliteSystem

_EPHEMERIS_LOGS: Mapping[SatelliteSystem, Log] = {
    SatelliteSystem.GPS: Log.GPSEPH,
    SatelliteSystem.GLONASS: Log.GLOEPH,
    SatelliteSystem.GALILEO: Log.GALEPH,
    SatelliteSystem.BEIDOU: Log.BDSEPH,
}


def receiver_position(record: Record) -> tuple[float, float, float]:
    """Observer ECEF from a BESTPOS or BESTXYZ record."""
    return receiver_ecef(record)


def build_payload(report: CrossCheckReport) -> dict[str, object]:
    """Render a cross-check report as JSON-ready data."""
    return {
        "status": "compared" if report.compared else "insufficient_data",
        "epoch": report.epoch,
        "direction_tolerance_degrees": DIRECTION_TOLERANCE_DEGREES,
        "rms_direction_error_degrees": report.rms_direction_error,
        "rms_azimuth_error_degrees": report.rms_azimuth_error,
        "rms_elevation_error_degrees": report.rms_elevation_error,
        "counts": {
            system.name: {
                "visibility": report.visibility_counts.get(system, 0),
                "ephemeris": report.ephemeris_counts.get(system, 0),
                "matched": report.matched_counts.get(system, 0),
            }
            for system in SatelliteSystem
            if report.visibility_counts.get(system, 0) > 0
        },
        "differences": [
            {
                "system": difference.system.name,
                "prn": native_number(difference.system, difference.prn),
                "wire_prn": difference.prn,
                "azimuth_error_degrees": difference.azimuth_error,
                "elevation_error_degrees": difference.elevation_error,
                "direction_error_degrees": difference.direction_error,
                "within_tolerance": difference.is_within_tolerance,
            }
            for difference in report.compared
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Cross-check broadcast azimuth/elevation against one SATVIS2 epoch."""
    parser = ExampleParser(
        prog="python -m examples.azel_crosscheck",
        description="Compare ephemeris azimuth/elevation with SATVIS2",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ephemeris",
        type=Path,
        default=None,
        help="captured GPSEPH/GLOEPH/GALEPH/BDSEPH frames for replay",
    )
    parser.add_argument(
        "--position",
        type=Path,
        default=None,
        help="captured BESTPOS or BESTXYZ frame for replay",
    )
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    parser.add_argument(
        "--position-tolerance",
        type=float,
        default=1.0,
        help="maximum receiver position epoch offset in seconds",
    )
    args = parser.parse_args(argv)
    debug_header(args, "azel_crosscheck")
    if args.replay is None:
        logs: list[Log] = [
            Log.SATVIS2,
            Log.BESTPOS,
            *_EPHEMERIS_LOGS.values(),
        ]
        captured = capture_records(
            args,
            logs,
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("azel_crosscheck") if args.debug else None,
        )
        satellite_records, position_records = captured["SATVIS2"], captured["BESTPOS"]
        ephemeris_frames = [
            record.message
            for log in _EPHEMERIS_LOGS.values()
            for record in captured[log.value]
            if record.message is not None
        ]
    else:
        satellite_frames = read_frames(args.replay)
        position_frames = (
            read_frames(args.position)
            if args.position is not None
            else satellite_frames
        )
        ephemeris_frames = (
            list(read_frames(args.ephemeris))
            if args.ephemeris is not None
            else list(satellite_frames)
        )
        satellite_records = decode_records(satellite_frames, Log.SATVIS2)
        position_records = tuple(
            record
            for log in (Log.BESTPOS, Log.BESTXYZ)
            for record in decode_records(position_frames, selected_log(args, log))
        )
    if not satellite_records:
        parser.error("SATVIS2 records are required")
    selected, position_record = select_position_pair(
        satellite_records, position_records, args.position_tolerance
    )
    first_satellite = selected.message
    if first_satellite is None:
        parser.error("SATVIS2 frame carries no timestamp")
    absolute_epoch = gps_epoch(first_satellite)
    epoch = absolute_epoch % WEEK_SECONDS
    satellite_records = tuple(
        record
        for record in satellite_records
        if record.message is not None
        and abs(gps_epoch(record.message) - absolute_epoch) < 1e-6
    )
    records_by_system = {
        system: decode_records(ephemeris_frames, log)
        for system, log in _EPHEMERIS_LOGS.items()
    }
    report = cross_check(
        records_by_system,
        satellite_records,
        receiver_position(position_record),
        epoch,
    )
    print(
        f"Az/el cross-check: RMS azimuth {report.rms_azimuth_error:.3f} deg, "
        f"RMS elevation {report.rms_elevation_error:.3f} deg over "
        f"{len(report.compared)} matched satellites",
        file=sys.stderr,
    )
    write_json(build_payload(report), args.json)
    return 0 if report.compared else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
