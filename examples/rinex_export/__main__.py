"""Export multi-GNSS RINEX 3.05 observations from one or both antenna inputs."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from um982py import export_rinex
from um982py.antenna import AntennaLog
from um982py.capture import capture_records, record_epoch
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.field_data import file_sha256
from um982py.messages import Record
from um982py.observation_quality import audit_observations
from um982py.rinex import RinexMetadata


def _shared_records(
    first: Sequence[Record], second: Sequence[Record]
) -> tuple[tuple[Record, ...], tuple[Record, ...]]:
    common = {record_epoch(item) for item in first} & {
        record_epoch(item) for item in second
    }
    return (
        tuple(item for item in first if record_epoch(item) in common),
        tuple(item for item in second if record_epoch(item) in common),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def _metadata(path: Path | None) -> RinexMetadata | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("metadata must be a JSON object")
    return RinexMetadata(**data)


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        prog="python -m examples.rinex_export",
        description="Export multi-GNSS RINEX 3.05 from RANGE observations",
    )
    add_receiver_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--marker-name", default="UM982")
    parser.add_argument("--metadata", type=Path, help="primary station metadata JSON")
    parser.add_argument(
        "--frames",
        type=int,
        help="maximum epochs (default: 60 live, all epochs when replaying)",
    )
    parser.add_argument("--source", choices=("range", "obsv"), default="range")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--duration", type=float, default=60.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    parser.add_argument("--l2c-code", choices=("2S", "2L", "2X"))
    parser.add_argument("--secondary", action="store_true")
    parser.add_argument("--secondary-output", type=Path)
    parser.add_argument("--secondary-marker", default="UM982-SLAVE")
    parser.add_argument(
        "--secondary-metadata", type=Path, help="secondary station metadata JSON"
    )
    args = parser.parse_args(argv)
    if args.frames is None and args.replay is None:
        args.frames = 60
    debug_header(args, "rinex_export")
    if args.secondary_output is not None and not args.secondary:
        parser.error("--secondary-output requires --secondary")
    if args.secondary_metadata is not None and not args.secondary:
        parser.error("--secondary-metadata requires --secondary")
    try:
        primary_metadata = _metadata(args.metadata)
        secondary_metadata = _metadata(args.secondary_metadata)
    except (OSError, ValueError, TypeError) as error:
        parser.error(f"invalid station metadata: {error}")
    if args.secondary and args.marker_name == args.secondary_marker:
        parser.error("the two antenna files need distinct marker names")
    other = args.secondary_output or args.output.with_name(
        f"{args.output.stem}-slave{args.output.suffix}"
    )
    destinations = [args.output]
    if args.secondary:
        destinations.append(other)
    if args.json is not None:
        destinations.append(args.json)
    if args.record is not None:
        destinations.append(args.record)
    if args.replay is not None:
        destinations.append(args.replay)
    if args.metadata is not None:
        destinations.append(args.metadata)
    if args.secondary_metadata is not None:
        destinations.append(args.secondary_metadata)
    if len({path.resolve() for path in destinations}) != len(destinations):
        parser.error("output, report, capture and metadata paths must be distinct")
    first_log, second_log = (
        (Log.OBSVM, Log.OBSVH)
        if args.source == "obsv"
        else (FirmwareLog.RANGE, FirmwareLog.RANGEH)
    )
    logs = (
        [
            AntennaLog(first_log, first_log),
            AntennaLog(second_log, second_log),
        ]
        if args.secondary
        else [first_log]
    )
    captured = capture_records(
        args,
        logs,
        frames=args.frames,
        interval=args.interval,
        duration=args.duration,
        on_progress=progress_printer("rinex_export") if args.debug else None,
    )
    primary = captured[first_log.value]
    secondary = captured.get(second_log.value, ())
    captured_counts = {name: len(records) for name, records in captured.items()}
    if args.secondary:
        primary, secondary = _shared_records(primary, secondary)
        if not primary:
            parser.error(
                "both antenna inputs need at least one shared observation epoch"
            )
    if not primary:
        parser.error("capture contains no requested observations")
    exports = [
        (
            args.output,
            export_rinex(
                primary,
                marker_name=args.marker_name,
                l2c_code=args.l2c_code,
                metadata=primary_metadata,
            ),
        )
    ]
    if args.secondary:
        exports.append(
            (
                other,
                export_rinex(
                    secondary,
                    marker_name=args.secondary_marker,
                    l2c_code=args.l2c_code,
                    metadata=secondary_metadata,
                ),
            )
        )
    for path, result in exports:
        _write(path, result.text)
        print(
            f"wrote {result.epochs} epochs and {result.satellite_records} "
            f"satellite records to {path}",
            file=sys.stderr,
        )
    payload = {
        "format": "RINEX 3.05",
        "provenance": {
            "schema": "um982py-rinex-provenance-1",
            "input_mode": "replay" if args.replay is not None else "live",
            "input_capture": (
                {"path": str(args.replay), "sha256": file_sha256(args.replay)}
                if args.replay is not None
                else {"path": str(args.record), "sha256": file_sha256(args.record)}
                if args.record is not None
                else None
            ),
            "capture_counts": captured_counts,
            "requested_capture": {
                "frames": args.frames,
                "interval_seconds": args.interval,
                "duration_seconds": args.duration,
            },
            "receiver_configuration": None,
            "receiver_configuration_note": "not read or verified by this export",
            "l2c_code_supplied_by_user": args.l2c_code,
        },
        "files": [
            {
                "path": str(path),
                "sha256": file_sha256(path),
                "epochs": result.epochs,
                "satellite_records": result.satellite_records,
                "signal_observations": result.signal_observations,
                "omitted": result.omitted,
                "input_log": records[0].name,
                "time_scale": "GPST",
                "first_epoch_gps_seconds": record_epoch(records[0]),
                "last_epoch_gps_seconds": record_epoch(records[-1]),
                "station_metadata_supplied_by_user": asdict(metadata)
                if metadata
                else None,
                "observation_quality": asdict(
                    audit_observations(
                        records,
                        expected_interval=args.interval
                        if args.replay is None
                        else None,
                    )
                ),
            }
            for (path, result), records, metadata in zip(
                exports,
                (primary, secondary),
                (primary_metadata, secondary_metadata),
                strict=False,
            )
        ],
    }
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
