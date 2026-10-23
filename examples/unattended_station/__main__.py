"""Record bounded research segments and retain a durable station journal."""

import argparse
import fcntl
import hashlib
import json
import math
import os
import shutil
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from examples.research_session.__main__ import main as record_session
from um982py.console import ExampleParser, add_receiver_arguments, run
from um982py.receiver import Receiver


def _snapshot(args: argparse.Namespace) -> dict[str, object] | None:
    if args.replay is not None:
        return None
    state: dict[str, object] = {"time_utc": datetime.now(UTC).isoformat()}
    try:
        with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
            try:
                version = receiver.version()
                state["firmware"] = {
                    "model": version.model,
                    "software": version.software,
                    "compiled": version.compiled,
                }
            except Exception as exc:
                state["firmware_error"] = str(exc)
            try:
                configuration = receiver.configuration()
                entries = sorted(configuration.entries)
                encoded = json.dumps(entries, ensure_ascii=True).encode("ascii")
                state["configuration"] = {
                    "entries_sha256": hashlib.sha256(encoded).hexdigest(),
                    "entry_count": len(entries),
                    "antenna_power": configuration.antenna_power,
                    "nmea_version": configuration.nmea_version,
                    "signal_group": str(configuration.signal_group)
                    if configuration.signal_group is not None
                    else None,
                }
            except Exception as exc:
                state["configuration_error"] = str(exc)
    except Exception as exc:
        state["connection_error"] = str(exc)
    return state


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description="Record resumable, bounded research segments")
    add_receiver_arguments(parser)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--segment-seconds", type=float, default=900)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument(
        "--segments",
        type=int,
        default=1,
        help="number of segments to capture, or 0 to run until interrupted",
    )
    parser.add_argument("--min-free-mib", type=float, default=512)
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=0,
        help="retry failed live segments after this delay, or stop when set to 0",
    )
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--secondary-metadata", type=Path)
    args = parser.parse_args(argv)
    if args.record is not None or args.json is not None:
        parser.error("segment recordings and journal are stored in --directory")
    if args.augment or args.swap_antennas or args.antenna not in ("primary", "1"):
        parser.error(
            "station recording requires unchanged primary and secondary inputs"
        )
    if (
        not math.isfinite(args.segment_seconds)
        or args.segment_seconds <= 0
        or not math.isfinite(args.interval)
        or args.interval <= 0
    ):
        parser.error("segment duration and interval must be finite and positive")
    if (
        args.segments < 0
        or not math.isfinite(args.min_free_mib)
        or args.min_free_mib < 0
        or not math.isfinite(args.retry_seconds)
        or args.retry_seconds < 0
    ):
        parser.error("segments and minimum free space must be non-negative")
    if args.replay is not None and args.segments != 1:
        parser.error("replay accepts exactly one segment")
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".station.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another station process owns this directory") from error
        return _record(args, directory)


def _record(args: argparse.Namespace, directory: Path) -> int:
    journal = directory / "station.jsonl"

    def write_event(event: dict[str, object]) -> None:
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    completed = 0
    while args.segments == 0 or completed < args.segments:
        free = shutil.disk_usage(directory).free
        if free < args.min_free_mib * 1048576:
            write_event(
                {
                    "status": "disk_low",
                    "free_bytes": free,
                    "time_utc": datetime.now(UTC).isoformat(),
                }
            )
            raise ValueError("insufficient free disk space for the next segment")
        counter = 1
        while (directory / f"segment-{counter:06d}").exists():
            counter += 1
        segment = directory / f"segment-{counter:06d}"
        segment.mkdir()
        started = datetime.now(UTC).isoformat()
        write_event(
            {
                "segment": segment.name,
                "started_utc": started,
                "status": "started",
                "free_bytes_before": free,
            }
        )
        command = [
            "--baud",
            str(args.baud),
            "--timeout",
            str(args.timeout),
            "--output-dir",
            str(segment),
            "--duration",
            str(args.segment_seconds),
            "--interval",
            str(args.interval),
        ]
        if args.replay is not None:
            command += ["--replay", str(args.replay)]
        elif args.port is not None:
            command += ["--port", args.port]
        for flag, value in (
            ("--metadata", args.metadata),
            ("--secondary-metadata", args.secondary_metadata),
        ):
            if value is not None:
                command += [flag, str(value)]
        error = None
        interrupted = False
        state_before = _snapshot(args)
        try:
            result = record_session(command)
        except KeyboardInterrupt:
            result, error, interrupted = 1, "interrupted", True
        except SystemExit as exc:
            result, error = 1, f"session exited with status {exc.code}"
        except Exception as exc:
            result, error = 1, str(exc)
        state_after = _snapshot(args) if not interrupted else None
        event = {
            "segment": segment.name,
            "started_utc": started,
            "finished_utc": datetime.now(UTC).isoformat(),
            "free_bytes_before": free,
            "status": "complete" if result == 0 else "failed",
            "error": error,
            "receiver_before": state_before,
            "receiver_after": state_after,
            "manifest": f"{segment.name}/manifest.json"
            if (segment / "manifest.json").is_file()
            else None,
        }
        write_event(event)
        if result != 0:
            if interrupted:
                raise KeyboardInterrupt
            if args.retry_seconds > 0 and args.replay is None:
                time.sleep(args.retry_seconds)
                continue
            return 1
        completed += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
