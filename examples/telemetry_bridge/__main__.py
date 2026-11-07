"""Stream decoded receiver frames as newline-delimited JSON."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator, Sequence
from math import isfinite
from pathlib import Path
from queue import Empty
from time import monotonic

from examples.telemetry_bridge import lines
from um982py.capture import iter_frames, open_receiver
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
)
from um982py.errors import TransportError
from um982py.streaming import ReceiverStream, Subscription


def _receiver_lines(
    stream: ReceiverStream, subscription: Subscription, seconds: float
) -> Iterator[str]:
    """Read subscribed messages and encode each one until the deadline."""
    deadline = monotonic() + seconds
    while (remaining := deadline - monotonic()) > 0:
        try:
            message = subscription.get(timeout=min(remaining, 0.2))
        except Empty:
            health = stream.health()
            if not health.running:
                raise TransportError(
                    f"receiver stream stopped: {health.failure}"
                ) from None
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
    if not isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be finite and positive")
    debug_header(args, "telemetry_bridge")
    if args.replay is None:
        receiver = open_receiver(args)
        stream = ReceiverStream(receiver)
        subscription = stream.subscribe()
        stream.start()
        try:
            count = _emit(
                _receiver_lines(stream, subscription, args.seconds), args.json
            )
        finally:
            stream.close(close_receiver=True)
        if subscription.dropped:
            print(f"Telemetry: {subscription.dropped} frames dropped", file=sys.stderr)
            return 1
    else:
        count = _emit(lines(iter_frames(Path(args.replay))), args.json)
    print(f"Telemetry: {count} frames bridged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
