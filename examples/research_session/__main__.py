"""Capture or replay a research session and export reproducible artifacts."""

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run
from um982py.field_data import file_sha256
from um982py.observation_quality import audit_observations
from um982py.rinex import RinexMetadata, export_rinex
from um982py.rinex_nav import export_rinex_navigation


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        description="Record OBSV, ephemeris and receiver time for research"
    )
    add_receiver_arguments(parser)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument(
        "--metadata", type=Path, help="primary antenna RINEX metadata JSON"
    )
    parser.add_argument("--secondary-metadata", type=Path)
    args = parser.parse_args(argv)
    if args.antenna not in ("primary", "1") or args.swap_antennas:
        parser.error("this paired session always captures primary and secondary inputs")
    if args.json is not None:
        parser.error("manifest is always written to OUTPUT-DIR/manifest.json")
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        parser.error("output directory must be empty")
    paths = [args.metadata, args.secondary_metadata]
    metadata: list[RinexMetadata | None] = []
    for path in paths:
        if path is None:
            metadata.append(None)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                parser.error("metadata must be a JSON object")
            metadata.append(RinexMetadata(**data))
    out.mkdir(parents=True, exist_ok=True)
    if args.replay is None and args.record is None:
        args.record = out / "capture.bin"
    destinations = [
        out / "primary.obs",
        out / "secondary.obs",
        out / "gps.nav",
        out / "manifest.json",
    ]
    paths_to_protect = [
        path
        for path in (args.replay, args.record, args.metadata, args.secondary_metadata)
        if path is not None
    ]
    if len({path.resolve() for path in destinations + paths_to_protect}) != len(
        destinations + paths_to_protect
    ):
        parser.error("capture, metadata and generated artifact paths must be distinct")
    logs = [
        Log.OBSVM,
        Log.OBSVH,
        Log.GPSEPH,
        Log.GALEPH,
        Log.GLOEPH,
        Log.BDSEPH,
        Log.BD3EPH,
        Log.BESTNAVXYZ,
        Log.RECTIME,
    ]
    captured = capture_records(
        args, logs, duration=args.duration, interval=args.interval
    )
    generated: dict[str, dict[str, object]] = {}
    for name, path, meta in (
        ("OBSVM", out / "primary.obs", metadata[0]),
        ("OBSVH", out / "secondary.obs", metadata[1]),
    ):
        records = captured[name]
        if not records:
            continue
        try:
            result = export_rinex(records, marker_name=name, metadata=meta)
        except ValueError as error:
            generated[name] = {"error": str(error)}
            continue
        path.write_text(result.text, encoding="ascii")
        generated[name] = {
            "path": path.name,
            "sha256": file_sha256(path),
            "epochs": result.epochs,
            "omitted": result.omitted,
            "quality": asdict(audit_observations(records)),
            "metadata_supplied_by_user": asdict(meta) if meta else None,
        }
    eph = captured["GPSEPH"]
    if eph:
        unique = tuple({record.entries: record for record in eph}.values())
        try:
            nav = export_rinex_navigation(unique)
        except ValueError as error:
            generated["GPSEPH"] = {"error": str(error)}
        else:
            path = out / "gps.nav"
            path.write_text(nav.text, encoding="ascii")
            generated["GPSEPH"] = {
                "path": path.name,
                "sha256": file_sha256(path),
                "messages": nav.messages,
                "unknown_fields": nav.unknown_fields,
            }
    input_path = args.replay if args.replay is not None else args.record
    manifest = {
        "schema": "um982py-research-session-1",
        "input_mode": "replay" if args.replay else "live",
        "raw_capture": {"path": str(input_path), "sha256": file_sha256(input_path)}
        if input_path
        else None,
        "capture_counts": {name: len(records) for name, records in captured.items()},
        "requested_interval_seconds": args.interval,
        "requested_duration_seconds": args.duration,
        "receiver_configuration": None,
        "receiver_firmware": None,
        "artifacts": generated,
        "limitations": [
            "Receiver configuration and firmware not queried",
            "GPS-only navigation export",
            "Antenna corrections not applied",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return (
        0
        if any(
            name in generated and "sha256" in generated[name]
            for name in ("OBSVM", "OBSVH")
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(run(main))
