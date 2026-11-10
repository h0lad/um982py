"""Configure and record a receiver stream as a replayable test dataset."""

import argparse
import json
import math
import shutil
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from tools.test_data_recorder.audit import LOGS, log_name
from tools.test_data_recorder.profile import select

from um982py import Receiver
from um982py.capture import RecordingTransport
from um982py.commands import Port
from um982py.errors import TransportError
from um982py.protocol import StreamDecoder
from um982py.session import SessionRecorder
from um982py.subscriptions import temporary_subscriptions
from um982py.transports.base import Transport
from um982py.transports.serial import SerialTransport


def _size(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def _duration(seconds: float) -> str:
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_status(values: dict) -> str:
    """Format one live status update without changing the recorded data."""
    elapsed = values["elapsed_seconds"]
    total = values["requested_seconds"]
    free = values.get("free_disk_bytes")
    free_text = _size(free) if free is not None else "unknown"
    data_age = values["data_age_seconds"]
    data_text = f"{data_age:.1f}s ago" if data_age is not None else "not received"
    lines = [
        f"[{_duration(elapsed)} / {_duration(total)}] "
        f"{min(100, elapsed * 100 / total):.1f}% | "
        f"remaining {_duration(total - elapsed)}",
        f"  Data: {_size(values['received_bytes'])} | "
        f"recent {_size(values['recent_bytes_per_second'])}/s | "
        f"average {_size(values['average_bytes_per_second'])}/s | "
        f"last {data_text} | free {free_text}",
    ]
    antennas = []
    for label, name in (("ANT1", "OBSVM"), ("ANT2", "OBSVH")):
        age = values["observation_age_seconds"][name]
        state = "not received" if age is None else f"{age:.1f}s ago"
        if age is not None and age > 5:
            state += ", stale"
        antennas.append(
            f"{label} {name}: {values['valid_frames'][name]} "
            f"(+{values['recent_frames'][name]}), {state}"
        )
    lines.append("  " + " | ".join(antennas))
    navigation = ", ".join(
        f"{name}={values['valid_frames'][name]}"
        for name in ("GPSEPH", "GLOEPH", "GALEPH", "BDSEPH", "BD3EPH", "QZSSEPH")
    )
    lines.append(f"  Ephemerides (total): {navigation}")
    frames = ", ".join(
        f"{name}={count}"
        for name, count in values["recent_frames"].items()
        if count and name not in ("OBSVM", "OBSVH")
    )
    lines.append(
        f"  Frames in last {values['window_seconds']:.1f}s: {frames or 'none'}"
    )
    lines.append(
        f"  Decoder: errors >= {values['decoder_errors_at_least']}, "
        f"discarded {values['discarded_bytes']} B, "
        f"pending {values['pending_bytes']} B | other {values['other_frames']}"
    )
    return "\n".join(lines)


def record(
    transport: Transport,
    recorder: SessionRecorder,
    duration: float,
    *,
    segment_seconds: float = 1800,
    status_seconds: float = 60,
    progress: Callable[[dict], None] | None = None,
    clock: Callable[[], float] = monotonic,
) -> dict:
    """Write received bytes before any decoding and report the outcome."""
    if not all(
        math.isfinite(value) and value > 0
        for value in (duration, segment_seconds, status_seconds)
    ):
        raise ValueError("duration and intervals must be finite and positive")
    started = datetime.now(UTC).isoformat()
    start = clock()
    last_flush = start
    last_status = start
    status_bytes = 0
    last_data: float | None = None
    next_segment = start + segment_seconds
    next_status = start + status_seconds
    received = 0
    decoder = StreamDecoder()
    counts = dict.fromkeys((log.value for log in LOGS), 0)
    status_counts = dict.fromkeys(counts, 0)
    last_seen: dict[str, float] = {}
    errors = other = 0
    status = "complete"

    def statistics(now: float) -> dict:
        elapsed = max(0.0, now - start)
        return {
            "elapsed_seconds": round(elapsed, 1),
            "requested_seconds": duration,
            "window_seconds": round(max(0.0, now - last_status), 1),
            "received_bytes": received,
            "average_bytes_per_second": round(received / elapsed, 1) if elapsed else 0,
            "recent_bytes_per_second": (
                round((received - status_bytes) / (now - last_status), 1)
                if now > last_status
                else 0
            ),
            "data_age_seconds": (
                round(now - last_data, 1) if last_data is not None else None
            ),
            "valid_frames": dict(counts),
            "recent_frames": {
                name: count - status_counts[name] for name, count in counts.items()
            },
            "observation_age_seconds": {
                name: round(now - last_seen[name], 1) if name in last_seen else None
                for name in ("OBSVM", "OBSVH")
            },
            "other_frames": other,
            "decoder_errors_at_least": errors,
            "discarded_bytes": decoder.discarded_bytes,
            "pending_bytes": len(decoder.pending),
        }

    try:
        while (remaining := duration - (clock() - start)) > 0:
            now = clock()
            data = transport.read(
                65536,
                max(0.0, min(1.0, remaining, next_segment - now, next_status - now)),
            )
            if data:
                recorder.write(data)
                received += len(data)
                now = clock()
                last_data = now
                for message in decoder.feed(data):
                    name = log_name(message)
                    if name is None:
                        other += 1
                    else:
                        counts[name] += 1
                        last_seen[name] = now
                errors += len(decoder.errors)
                decoder.errors.clear()
            now = clock()
            if now - last_flush >= 5:
                recorder.flush()
                last_flush = now
            if now >= next_segment:
                recorder.rotate()
                next_segment = now + segment_seconds
            if now >= next_status:
                if progress is not None:
                    progress(statistics(now))
                last_status = now
                status_bytes = received
                status_counts = dict(counts)
                next_status = now + status_seconds
    except KeyboardInterrupt:
        status = "interrupted"
    except TransportError as error:
        status = "transport_error"
        recorder.mark_gap(f"{type(error).__name__}: {error}"[:1024])
    if status == "complete" and not received:
        status = "no_data"
    return {
        "schema": "um982py-recording-report-1",
        "status": status,
        "started_at": started,
        "ended_at": datetime.now(UTC).isoformat(),
        **statistics(clock()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="host serial device")
    parser.add_argument("directory", type=Path, help="new recording directory")
    parser.add_argument(
        "--receiver-port",
        required=True,
        choices=[port.value for port in Port],
        help="receiver COM port connected to the host",
    )
    parser.add_argument("--compressed", action="store_true")
    parser.add_argument("--corrections", action="store_true")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--duration", type=float, default=86400, help="seconds")
    parser.add_argument("--segment-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--segment-seconds", type=float, default=1800)
    parser.add_argument("--status-seconds", type=float, default=60)
    parser.add_argument("--status-format", choices=("text", "json"), default="text")
    parser.add_argument("--metadata", type=Path, help="JSON object with field notes")
    parser.add_argument(
        "--no-fsync", action="store_true", help="skip syncing completed segments"
    )
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.duration)
        or args.duration <= 0
        or args.baud <= 0
        or args.segment_bytes <= 0
        or not math.isfinite(args.segment_seconds)
        or args.segment_seconds <= 0
        or not math.isfinite(args.status_seconds)
        or args.status_seconds <= 0
    ):
        parser.error("duration, baud, segment size and intervals must be positive")
    metadata = (
        json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    )
    if not isinstance(metadata, dict):
        parser.error("metadata must be a JSON object")

    port = Port(args.receiver_port)
    planned = tuple(
        (log.wire_name(binary=True), log.output(interval, binary=True, port=port))
        for log, interval in select(
            compressed=args.compressed, corrections=args.corrections
        )
    )
    report: dict | None = None
    failure: Exception | None = None
    with SessionRecorder(
        args.directory,
        metadata={
            "port": args.port,
            "baud": args.baud,
            "receiver_port": port.value,
            "commands": [command.text for _, command in planned],
            "notes": metadata,
        },
        segment_bytes=args.segment_bytes,
        fsync=not args.no_fsync,
    ) as recorder:
        transport = SerialTransport(args.port, args.baud)
        receiver = Receiver(RecordingTransport(transport, recorder, close_stream=False))
        try:

            def show_status(values: dict) -> None:
                try:
                    values["free_disk_bytes"] = shutil.disk_usage(args.directory).free
                except OSError:
                    values["free_disk_bytes"] = None
                print(
                    json.dumps(values, separators=(",", ":"))
                    if args.status_format == "json"
                    else format_status(values),
                    file=sys.stderr,
                    flush=True,
                )

            try:
                print("Configuring receiver outputs.", file=sys.stderr)
                with temporary_subscriptions(receiver, *planned):
                    print(
                        "Recording stream; press Ctrl-C to stop early.", file=sys.stderr
                    )
                    try:
                        report = record(
                            transport,
                            recorder,
                            args.duration,
                            segment_seconds=args.segment_seconds,
                            status_seconds=args.status_seconds,
                            progress=show_status,
                        )
                    finally:
                        # The raw recorder consumed the stream independently.
                        receiver.drain_pending()
                        receiver.decoder.reset()
                if report is not None:
                    report["subscriptions_restored"] = True
            except Exception as error:
                failure = error
                if report is not None:
                    report["subscriptions_restored"] = False
        finally:
            receiver.close()
    if report is None:
        if failure is not None:
            raise failure
        raise RuntimeError("recording did not start")
    (args.directory / "capture.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if failure is not None:
        raise failure
    print(f"Recording {report['status']}: {report['received_bytes']} bytes.")
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
