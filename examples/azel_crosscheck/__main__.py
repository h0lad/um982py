"""Command line driver for the azimuth/elevation cross-check example."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path

from examples.azel_crosscheck import (
    AZIMUTH_TOLERANCE_DEGREES,
    ELEVATION_TOLERANCE_DEGREES,
    CrossCheckReport,
    cross_check,
)
from um982py.capture import capture_records, read_frames
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.geodesy import receiver_ecef
from um982py.messages import (
    AsciiHeader,
    AsciiMessage,
    BinaryHeader,
    BinaryMessage,
    LegacyAsciiHeader,
    LegacyBinaryHeader,
    Message,
    Record,
)
from um982py.messages.enums import SatelliteSystem

_EPHEMERIS_LOGS: Mapping[SatelliteSystem, Log] = {
    SatelliteSystem.GPS: Log.GPSEPH,
    SatelliteSystem.GLONASS: Log.GLOEPH,
    SatelliteSystem.GALILEO: Log.GALEPH,
    SatelliteSystem.BEIDOU: Log.BDSEPH,
}


def epoch_seconds(message: Message) -> float:
    """Receiver time of week in seconds from any stamped data frame."""
    if not isinstance(message, (AsciiMessage, BinaryMessage)):
        raise ValueError("message carries no timestamp")
    header = message.header
    if isinstance(header, (AsciiHeader, BinaryHeader)):
        return header.milliseconds / 1000.0
    if isinstance(header, LegacyBinaryHeader):
        return int.from_bytes(header.raw[16:20], "little") / 1000.0
    if isinstance(header, LegacyAsciiHeader):
        return float(header.fields[5])
    raise ValueError("message carries no timestamp")


def receiver_position(record: Record) -> tuple[float, float, float]:
    """Observer ECEF from a BESTPOS or BESTXYZ record."""
    return receiver_ecef(record)


def _decode(frames: Sequence[Message], log: Log) -> tuple[Record, ...]:
    decoded: list[Record] = []
    for message in frames:
        with suppress(ProtocolError):
            decoded.append(log.decode(message))
    return tuple(decoded)


def _decode_firmware(frames: Sequence[Message], log: FirmwareLog) -> tuple[Record, ...]:
    decoded: list[Record] = []
    for message in frames:
        with suppress(ProtocolError):
            decoded.append(log.decode(message))
    return tuple(decoded)


def _first_decoded(frames: Sequence[Message], log: FirmwareLog) -> Record | None:
    return next(iter(_decode_firmware(frames, log)), None)


def _single_position(frames: Sequence[Message]) -> Record | None:
    for log in (FirmwareLog.BESTPOS, FirmwareLog.BESTXYZ):
        record = _first_decoded(frames, log)
        if record is not None:
            return record
    return None


def build_payload(report: CrossCheckReport) -> dict[str, object]:
    """Render a cross-check report as JSON-ready data."""
    return {
        "epoch": report.epoch,
        "azimuth_tolerance_degrees": AZIMUTH_TOLERANCE_DEGREES,
        "elevation_tolerance_degrees": ELEVATION_TOLERANCE_DEGREES,
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
                "prn": difference.prn,
                "azimuth_error_degrees": difference.azimuth_error,
                "elevation_error_degrees": difference.elevation_error,
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
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "azel_crosscheck")
    if args.replay is None:
        logs: list[Log | FirmwareLog] = [
            FirmwareLog.SATVIS2,
            FirmwareLog.BESTPOS,
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
        satellite_records = _decode_firmware(satellite_frames, FirmwareLog.SATVIS2)
        position_records = tuple(
            record
            for record in (_single_position(position_frames),)
            if record is not None
        )
    position_record = position_records[0] if position_records else None
    if not satellite_records or position_record is None:
        parser.error("SATVIS2 and a BESTPOS/BESTXYZ frame are required")
    first_satellite = satellite_records[0].message
    if first_satellite is None:
        parser.error("SATVIS2 frame carries no timestamp")
    epoch = epoch_seconds(first_satellite)
    satellite_records = tuple(
        record
        for record in satellite_records
        if record.message is not None
        and abs(epoch_seconds(record.message) - epoch) < 1e-6
    )
    records_by_system = {
        system: _decode(ephemeris_frames, log)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
