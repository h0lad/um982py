"""Runs the telemetry bridge example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from time import monotonic

from examples.telemetry_bridge import lines
from um982py.capture import open_receiver, read_frames
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
)
from um982py.errors import ResponseTimeout
from um982py.receiver import Receiver


def _receiver_lines(receiver: Receiver, seconds: float) -> Iterator[str]:
    """Read frames from an open receiver for ``seconds`` and encode each one."""
    deadline = monotonic() + seconds
    while (remaining := deadline - monotonic()) > 0:
        try:
            message = receiver.receive(timeout=min(remaining, 1.0))
        except ResponseTimeout:
            continue
        yield from lines((message,))


def _emit(encoded: Iterable[str], destination: Path | None) -> int:
    """Write the encoded frames to a file, or to stdout."""
    count = 0
    if destination is None:
        for line in encoded:
            print(line, flush=True)
            count += 1
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as stream:
            for line in encoded:
                stream.write(line + "\n")
                stream.flush()
                count += 1
    return count


def main(argv: Sequence[str] | None = None) -> int:
    """Bridge decoded frames to newline-delimited JSON."""
    parser = ExampleParser(
        prog="python -m examples.telemetry_bridge", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--seconds", type=float, default=10.0, help="streaming duration in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "telemetry_bridge")
    if args.replay is None:
        receiver = open_receiver(args)
        try:
            count = _emit(_receiver_lines(receiver, args.seconds), args.json)
        finally:
            receiver.close()
    else:
        count = _emit(lines(read_frames(Path(args.replay))), args.json)
    print(f"Telemetry: {count} frames bridged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
