# Audit RANGECMP compression against full RANGE observations.

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from examples._console import (
    ExampleParser,
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from examples._console_capture import open_receiver
from examples.compressed_observation_audit import agree_epoch, summarise_epochs
from examples.compressed_observation_audit.rangecmp2 import report_gps_l1
from um982py.antenna import antenna_index
from um982py.capture import epoch_seconds, iter_frames
from um982py.commands import Log
from um982py.errors import ResponseTimeout
from um982py.experimental import (
    decode_rangecmp,
    decode_rangecmp2,
    rangecmp2_output,
    rangecmp2_read,
    rangecmp_output,
    rangecmp_read,
)
from um982py.messages import BinaryMessage
from um982py.subscriptions import temporary_subscriptions


def _parser() -> ExampleParser:
    parser = experiment_parser(
        "compressed_observation_audit",
        "RANGECMP agreement with RANGE and its wire-size ratio.",
    )
    parser.add_argument(
        "--rangecmp2",
        action="store_true",
        help="Audit GPS L1 code and L2 phase anchors",
    )
    add_debug_argument(parser)
    return parser


def _collect_live_range_frames(
    args: argparse.Namespace,
    range_log: Log,
    antenna: int,
) -> tuple[list[BinaryMessage], list[BinaryMessage]]:
    range_frames: list[BinaryMessage] = []
    compressed_frames: list[BinaryMessage] = []
    full = range_log.request(binary=True)
    read = rangecmp2_read if args.rangecmp2 else rangecmp_read
    output = rangecmp2_output if args.rangecmp2 else rangecmp_output
    compressed = read(antenna=antenna)
    with (
        open_receiver(args) as receiver,
        temporary_subscriptions(
            receiver,
            (full.text, range_log.output(args.interval, binary=True)),
            (compressed.text, output(args.interval, antenna=antenna)),
        ),
    ):
        deadline = monotonic() + args.duration
        while monotonic() < deadline:
            try:
                message = receiver.receive(timeout=max(0.01, deadline - monotonic()))
            except ResponseTimeout:
                continue
            if not isinstance(message, BinaryMessage):
                continue
            if full.matches(message):
                range_frames.append(message)
            elif compressed.matches(message):
                compressed_frames.append(message)
    return range_frames, compressed_frames


def _split_replayed_range_frames(
    path: Path,
    range_log: Log,
    antenna: int,
    *,
    second_generation: bool,
) -> tuple[list[BinaryMessage], list[BinaryMessage]]:
    range_frames: list[BinaryMessage] = []
    compressed_frames: list[BinaryMessage] = []
    full = range_log.request(binary=True)
    read = rangecmp2_read if second_generation else rangecmp_read
    compressed = read(antenna=antenna)
    for message in iter_frames(path):
        if not isinstance(message, BinaryMessage):
            continue
        if full.matches(message):
            range_frames.append(message)
        elif compressed.matches(message):
            compressed_frames.append(message)
    return range_frames, compressed_frames


def main(argv: Sequence[str] | None = None) -> int:
    """Compare RANGECMP reconstructions with RANGE over shared epochs."""
    parser = _parser()
    args = parser.parse_args(argv)
    debug_header(args, "compressed_observation_audit")
    antenna = antenna_index(args.antenna)
    if args.swap_antennas:
        antenna = 3 - antenna
    range_log = Log.RANGE if antenna == 1 else Log.RANGEH
    if args.replay is not None:
        range_frames, compressed_frames = _split_replayed_range_frames(
            args.replay, range_log, antenna, second_generation=args.rangecmp2
        )
    else:
        if args.record is not None and args.record.exists():
            parser.error("record path must not exist")
        range_frames, compressed_frames = _collect_live_range_frames(
            args, range_log, antenna
        )
    ranges = {epoch_seconds(frame): frame for frame in range_frames}
    compressed_ranges = {epoch_seconds(frame): frame for frame in compressed_frames}
    shared = ranges.keys() & compressed_ranges.keys()
    if not shared:
        family = "RANGECMP2" if args.rangecmp2 else "RANGECMP"
        parser.error(f"capture contains no shared RANGE and {family} epochs")
    unmatched = {
        "unpaired_range_epochs": len(ranges) - len(shared),
        "unpaired_compressed_epochs": len(compressed_ranges) - len(shared),
    }
    if args.rangecmp2:
        report = report_gps_l1(
            [
                (
                    epoch,
                    range_log.decode(ranges[epoch]),
                    decode_rangecmp2(compressed_ranges[epoch]),
                    len(ranges[epoch].raw),
                )
                for epoch in sorted(shared)
            ]
        )
        write_json({"antenna": antenna, **unmatched, **report}, args.json)
        return 0
    epochs = []
    for epoch in sorted(shared):
        range_frame, compressed_frame = ranges[epoch], compressed_ranges[epoch]
        reference = range_log.decode(range_frame)
        compressed = decode_rangecmp(compressed_frame)
        epochs.append(
            agree_epoch(
                reference.records("observations"),
                compressed.observations,
                range_bytes=len(range_frame.raw),
                compressed_bytes=len(compressed_frame.raw),
            )
        )
    summary = summarise_epochs(epochs)
    payload = {
        "antenna": antenna,
        "epochs": [asdict(epoch) for epoch in epochs],
        **unmatched,
        "summary": asdict(summary),
    }
    print(
        f"Compressed observation audit: {summary.matched} matched in "
        f"{summary.epochs} epochs, worst phase "
        f"{summary.worst_phase_cycles} cycles, "
        f"wire ratio {summary.ratio:.3f}",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
