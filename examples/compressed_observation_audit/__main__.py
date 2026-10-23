"""Audit RANGECMP compression against full RANGE observations."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from examples.compressed_observation_audit import agree_epoch, summarise_epochs
from um982py.capture import open_receiver, read_frames
from um982py.console import (
    ExampleParser,
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout
from um982py.experimental import FirmwareLog, decode_rangecmp, rangecmp_output
from um982py.messages import BinaryMessage, Record
from um982py.subscriptions import temporary_subscriptions

_RANGE_ID = 43
_RANGECMP_ID = 140


def _parser() -> ExampleParser:
    parser = experiment_parser(
        "compressed_observation_audit",
        "RANGECMP agreement with RANGE and its wire-size ratio.",
    )
    add_debug_argument(parser)
    return parser


def _collect_live(
    args: argparse.Namespace,
) -> tuple[list[BinaryMessage], list[BinaryMessage]]:
    """Subscribe to RANGE and RANGECMP and collect both streams."""
    receiver = open_receiver(args)
    range_frames: list[BinaryMessage] = []
    compressed_frames: list[BinaryMessage] = []
    recorder = args.record.open("wb") if args.record is not None else None
    try:
        with temporary_subscriptions(
            receiver,
            ("RANGEB", FirmwareLog.RANGE.output(args.interval, binary=True)),
            ("RANGECMPB", rangecmp_output(args.interval)),
        ):
            deadline = monotonic() + args.duration
            while monotonic() < deadline:
                try:
                    message = receiver.receive(
                        timeout=max(0.01, deadline - monotonic())
                    )
                except ResponseTimeout:
                    continue
                if (
                    isinstance(message, BinaryMessage)
                    and message.header.message_id == _RANGE_ID
                ):
                    range_frames.append(message)
                elif (
                    isinstance(message, BinaryMessage)
                    and message.header.message_id == _RANGECMP_ID
                ):
                    compressed_frames.append(message)
                else:
                    continue
                if recorder is not None:
                    recorder.write(message.raw)
    finally:
        if recorder is not None:
            recorder.close()
        receiver.close()
    return range_frames, compressed_frames


def _split_replay(path: Path) -> tuple[list[BinaryMessage], list[BinaryMessage]]:
    """Split replayed wire frames into RANGE and RANGECMP streams."""
    range_frames: list[BinaryMessage] = []
    compressed_frames: list[BinaryMessage] = []
    for message in read_frames(path):
        if not isinstance(message, BinaryMessage):
            continue
        if message.header.message_id == _RANGE_ID:
            range_frames.append(message)
        elif message.header.message_id == _RANGECMP_ID:
            compressed_frames.append(message)
    return range_frames, compressed_frames


def _lookup(record: Record) -> dict[int, Record]:
    """Index RANGE observations by tracking status."""
    return {
        observation.integer("tracking_status"): observation
        for observation in record.records("observations")
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Compare RANGECMP reconstructions with RANGE over shared epochs."""
    parser = _parser()
    args = parser.parse_args(argv)
    debug_header(args, "compressed_observation_audit")
    if args.replay is not None:
        range_frames, compressed_frames = _split_replay(args.replay)
    else:
        if args.record is not None and args.record.exists():
            parser.error("record path must not exist")
        range_frames, compressed_frames = _collect_live(args)
    if not range_frames or not compressed_frames:
        parser.error("capture contains no shared RANGE and RANGECMP epochs")
    epochs = []
    for range_frame, compressed_frame in zip(
        range_frames, compressed_frames, strict=False
    ):
        reference = FirmwareLog.RANGE.decode(range_frame)
        compressed = decode_rangecmp(compressed_frame)
        epochs.append(
            agree_epoch(
                _lookup(reference),
                compressed.observations,
                range_bytes=len(range_frame.raw),
                compressed_bytes=len(compressed_frame.raw),
            )
        )
    summary = summarise_epochs(epochs)
    payload = {
        "epochs": [asdict(epoch) for epoch in epochs],
        "unpaired_range_epochs": len(range_frames) - len(epochs),
        "unpaired_compressed_epochs": len(compressed_frames) - len(epochs),
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
