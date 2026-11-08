"""Inspect kernel PPS edge timestamps on a configured Linux device."""

import argparse
from pathlib import Path

from um982py import PpsDevice, PpsEdge


def describe(edge: PpsEdge | None) -> str:
    if edge is None:
        return "unavailable"
    return f"seq={edge.sequence} realtime={edge.seconds}.{edge.nanoseconds:09d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=Path, default=Path("/dev/pps0"))
    parser.add_argument("--count", type=int, default=5, help="number of snapshots")
    parser.add_argument("--timeout", type=float, default=2.0, help="seconds per fetch")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be positive")
    with PpsDevice(args.device) as device:
        for _ in range(args.count):
            snapshot = device.fetch(timeout=args.timeout)
            print(
                f"assert {describe(snapshot.assert_edge)}; "
                f"clear {describe(snapshot.clear_edge)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
