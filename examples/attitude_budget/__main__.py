"""Runs the heading accuracy budget example from the command line."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

from examples.attitude_budget import (
    AttitudeBudget,
    Baseline,
    component_budget,
    required_baseline,
)
from um982py import Receiver
from um982py.antenna import antenna_log
from um982py.capture import DataLog, open_receiver, read_frames
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def _records(paths: Sequence[Path], log: DataLog) -> tuple[Record, ...]:
    """Decode one log from every captured transcript given."""
    decoded = []
    for path in paths:
        for message in read_frames(path):
            for binary in (True, False):
                if log.request(binary=binary).matches(message):
                    decoded.append(log.decode(message))
                    break
    return tuple(decoded)


def _queried(receiver: Receiver, log: DataLog) -> tuple[Record, ...]:
    """Query one log in its ASCII form."""
    try:
        print(f"Querying {log.value}...", file=sys.stderr, flush=True)
        return receiver.collect(log.read(binary=False))
    except ResponseTimeout:
        return ()


def _budget(
    baselines: Sequence[Record],
    positions: Sequence[Record],
    *,
    swapped: bool = False,
) -> AttitudeBudget | None:
    """Budget of the last baseline and position pair."""
    if not baselines:
        return None
    if all(key in baselines[-1] for key in ("std_1", "std_2", "std_3")):
        record = baselines[-1]
        baseline = Baseline.from_record(record)
        return component_budget(
            baseline.negated() if swapped else baseline,
            record.real("std_1"),
            record.real("std_2"),
            record.real("std_3"),
        )
    return None


def _payload(
    budget: AttitudeBudget | None, offsets: Sequence[Record]
) -> dict[str, object]:
    """Report of the budget, its inverse and the applied mount offset."""
    if budget is None:
        return {"budget": None}
    offset = offsets[-1].real("heading") if offsets else 0.0
    return {
        "budget": {
            "heading": budget.heading,
            "pitch": budget.pitch,
            "heading_sigma": budget.heading_sigma,
            "pitch_sigma": budget.pitch_sigma,
            "baseline_length": budget.baseline_length,
            "horizontal_length": budget.horizontal_length,
            "resolvable": budget.resolvable,
        },
        "offset": {
            "heading": offset,
            "reported_heading": budget.with_offset(offset).heading,
        },
        "required_baseline": {
            "one_degree": required_baseline(
                math.radians(budget.heading_sigma) * budget.horizontal_length, 1.0
            )
        },
        "uncertainty_source": "independent ENU baseline component sigmas",
    }


def _paths(args: argparse.Namespace) -> list[Path] | None:
    """Transcripts to replay, or ``None`` when the device answers instead."""
    if args.replay is not None:
        return [Path(args.replay)]
    if args.transcripts is not None:
        return sorted(Path(args.transcripts).glob("*.bin"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Replay transcripts or query the receiver, then report the budget."""
    parser = ExampleParser(
        prog="python -m examples.attitude_budget", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--transcripts",
        type=Path,
        default=None,
        help="directory of captured transcripts to replay",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "attitude_budget")
    paths = _paths(args)
    if paths is not None:
        budget = _budget(
            _records(paths, FirmwareLog.BSLNENUHD),
            _records(paths, antenna_log(FirmwareLog.BESTPOS, args.antenna)),
            swapped=args.swap_antennas,
        )
        offsets = _records(paths, FirmwareLog.HEADINGOFFSET)
    else:
        receiver = open_receiver(args)
        try:
            budget = _budget(
                _queried(receiver, FirmwareLog.BSLNENUHD),
                _queried(receiver, antenna_log(FirmwareLog.BESTPOS, args.antenna)),
                swapped=args.swap_antennas,
            )
            offsets = _queried(receiver, FirmwareLog.HEADINGOFFSET)
        finally:
            receiver.close()
    payload = _payload(budget, offsets)
    if budget is not None:
        print(
            f"Attitude budget: heading sigma {budget.heading_sigma:.4f} deg, "
            f"pitch sigma {budget.pitch_sigma:.4f} deg, "
            f"baseline {budget.baseline_length:.3f} m",
            file=sys.stderr,
        )
    else:
        print("Attitude budget: no baseline solution", file=sys.stderr)
    write_json(payload, args.json)
    return 0 if budget is not None else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
