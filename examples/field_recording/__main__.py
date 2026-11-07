"""Record receiver bytes in segments or replay a completed session."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

from um982py import Receiver, SessionRecorder, iter_session_frames
from um982py.capture import RecordingTransport
from um982py.errors import ResponseTimeout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    record = subparsers.add_parser("record", help="record currently enabled logs")
    record.add_argument("target", help="serial port or tcp://host:port")
    record.add_argument("directory", type=Path)
    record.add_argument("--baud", type=int, default=115200)
    record.add_argument("--duration", type=float, default=60)
    record.add_argument("--segment-bytes", type=int, default=64 * 1024 * 1024)
    record.add_argument("--metadata", type=Path, help="JSON object with field notes")
    replay = subparsers.add_parser("replay", help="verify and decode a session")
    replay.add_argument("directory", type=Path)
    replay.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "replay":
        for frame in iter_session_frames(
            args.directory, allow_incomplete=args.allow_incomplete
        ):
            print(frame)
        return 0

    if not 0 < args.duration < float("inf"):
        raise ValueError("duration must be finite and positive")
    metadata = (
        json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    )
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object")
    with (
        SessionRecorder(
            args.directory, metadata=metadata, segment_bytes=args.segment_bytes
        ) as recorder,
        Receiver.connect(args.target, args.baud) as receiver,
    ):
        receiver.transport = RecordingTransport(receiver.transport, recorder)
        deadline = monotonic() + args.duration
        while (remaining := deadline - monotonic()) > 0:
            try:
                receiver.receive(timeout=min(remaining, 1))
            except ResponseTimeout:
                continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
