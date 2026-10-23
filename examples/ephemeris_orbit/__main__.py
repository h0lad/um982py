"""Propagate every captured ephemeris to a satellite position and sky view."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from examples.ephemeris_orbit import state_from_record
from um982py import Receiver
from um982py.capture import decode_records, open_receiver, read_frames
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ProtocolError, ResponseTimeout
from um982py.messages import Record

EPHEMERIS = ("GPSEPH", "GALEPH", "BDSEPH", "GLOEPH")

__all__ = ["main"]


def collect(receiver: Receiver, seconds: float) -> dict[str, list[Record]]:
    """Collect ephemeris records for every constellation."""
    seen: dict[str, list[Record]] = {name: [] for name in EPHEMERIS}
    for name in EPHEMERIS:
        print(f"Querying {name} (up to {seconds:g}s)...", file=sys.stderr, flush=True)
        log = Log(name)
        command = log.request()
        try:
            for message in receiver.collect(command, timeout=seconds):
                try:
                    seen[name].append(log.decode(message))
                except (ValueError, ProtocolError):
                    continue
        except ResponseTimeout:
            continue
    return seen


def report(records: dict[str, list[Record]], seconds: float) -> dict[str, object]:
    """Propagate each record and summarise the constellation state."""
    satellites = []
    for name, entries in records.items():
        for record in entries:
            try:
                state = state_from_record(record, seconds)
            except (KeyError, ValueError):
                continue
            satellites.append(
                {
                    "constellation": name.removesuffix("EPH"),
                    "position": [
                        round(state.x, 1),
                        round(state.y, 1),
                        round(state.z, 1),
                    ],
                    "radius": round(state.radius, 1),
                    "clock_bias": state.clock_bias,
                }
            )
    return {"seconds": seconds, "satellites": satellites}


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        prog="python -m examples.ephemeris_orbit", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--seconds",
        dest="offset",
        type=float,
        default=30.0,
        help="seconds from ephemeris reference, including zero or negative offsets",
    )
    parser.add_argument(
        "--duration", type=float, default=3.0, help="maximum wait for each live query"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "ephemeris_orbit")
    records: dict[str, list[Record]]
    if args.replay is not None:
        frames = read_frames(args.replay)
        records = {name: list(decode_records(frames, Log(name))) for name in EPHEMERIS}
    else:
        with open_receiver(args) as receiver:
            records = collect(receiver, args.duration)
    payload = report(records, args.offset)
    satellites = payload["satellites"]
    print(
        f"Ephemeris orbit: "
        f"{len(satellites) if isinstance(satellites, list) else 0} propagated states",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
