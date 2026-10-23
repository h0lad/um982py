"""Runs the raw data tracking example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.raw_data_tracking import (
    catalogue_summary,
    field_coverage,
    report,
)
from um982py.capture import open_receiver
from um982py.commands.types import Port, Trigger
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.experimental import BasebandCapture, RawDataLog, capture_baseband


def main(argv: Sequence[str] | None = None) -> int:
    """Capture or replay raw bytes and report the containers they hold."""
    parser = ExampleParser(
        prog="python -m examples.raw_data_tracking", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--seconds", type=float, default=3.0, help="capture duration in seconds"
    )
    parser.add_argument("--raw-log", choices=list(RawDataLog), default="RAWBBPKG")
    parser.add_argument("--log-port", choices=list(Port), default="COM1")
    parser.add_argument("--on-changed", action="store_true")
    parser.add_argument(
        "--enable-gate",
        action="store_true",
        help="enable BBMSG2AP for capture, then disable it. The prior state is unknown",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "raw_data_tracking")
    if args.replay is None:
        receiver = open_receiver(args)
        try:
            capture = capture_baseband(
                receiver,
                args.raw_log,
                seconds=args.seconds,
                interval=Trigger.ON_CHANGED if args.on_changed else 1,
                port=Port(args.log_port),
                enable_gate=args.enable_gate,
            )
        finally:
            receiver.close()
    else:
        capture = BasebandCapture.from_bytes(Path(args.replay).read_bytes())
    payload = report(capture.raw).manifest()
    payload["status"] = "ok" if payload.get("container_count") else "insufficient_data"
    payload["capture"] = capture.manifest()
    payload["iq_samples_verified"] = False
    payload["catalogue"] = catalogue_summary().manifest()
    payload["field_coverage"] = asdict(field_coverage())
    containers = payload["container_count"]
    messages = payload["message_count"]
    print(
        f"Raw data: "
        f"{containers if isinstance(containers, int) else '?'} containers, "
        f"{messages if isinstance(messages, int) else '?'} messages; "
        "IQ unverified",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0 if payload.get("container_count") else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
