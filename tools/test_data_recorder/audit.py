"""Verify and summarize a recorded receiver session."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from tools.test_data_recorder.profile import TRACKED

from um982py.messages import BinaryMessage, Message
from um982py.protocol import StreamDecoder
from um982py.session import iter_session_bytes

LOGS = tuple(log for log, _ in TRACKED)
NAMES_BY_ID = {log.definition.message_id: log.value for log in LOGS}


def log_name(message: Message) -> str | None:
    """Identify tracked binary logs, including ONCHANGED-only logs."""
    if isinstance(message, BinaryMessage):
        return NAMES_BY_ID.get(message.header.message_id)
    return None


def audit(directory: Path) -> dict:
    """Check segment hashes and count decoded frames without retaining them."""
    journal = (directory / "segments.jsonl").read_text(encoding="utf-8")
    if any("gap" in json.loads(line) for line in journal.splitlines()):
        raise ValueError("session contains a gap; inspect its journal before replay")
    decoder = StreamDecoder()
    counts = dict.fromkeys((log.value for log in LOGS), 0)
    other = received = errors = 0
    for data in iter_session_bytes(directory):
        received += len(data)
        for message in decoder.feed(data):
            name = log_name(message)
            if name is None:
                other += 1
            else:
                counts[name] += 1
        # The decoder retains at most 32 errors per chunk.
        errors += len(decoder.errors)
        decoder.errors.clear()
    return {
        "schema": "um982py-session-audit-1",
        "received_bytes": received,
        "valid_frames": counts,
        "other_frames": other,
        "decoder_errors_at_least": errors,
        "discarded_bytes": decoder.discarded_bytes,
        "pending_bytes": len(decoder.pending),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--export", type=Path, help="write verified bytes to a new file"
    )
    args = parser.parse_args(argv)
    report = audit(args.directory)
    if args.export is not None:
        with args.export.open("xb") as output:
            for data in iter_session_bytes(args.directory):
                output.write(data)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
