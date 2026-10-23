"""Runs the baseband notice console example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.baseband_notice_console import apply_notices, solution_summary
from um982py.capture import open_receiver
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import CommandRejected
from um982py.experimental import BasebandNotice, capture_baseband_notices, scan_notices


def _payload(notices: Sequence[BasebandNotice]) -> dict[str, object]:
    """State payload for one replayed notice stream."""
    return {
        "notices": [notice.name for notice in notices],
        "state": asdict(apply_notices(notices)),
        "solutions": solution_summary(notices),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Replay a captured notice stream, or listen for one, and report the state."""
    parser = ExampleParser(
        prog="python -m examples.baseband_notice_console", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--seconds", type=float, default=3.0, help="listen time in seconds"
    )
    parser.add_argument(
        "--enable-gate",
        action="store_true",
        help="enable BBMSG2AP, then disable it without prior-state readback",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "baseband_notice_console")
    capture = None
    if args.replay is not None:
        notices = scan_notices(Path(args.replay).read_bytes())
    else:
        receiver = open_receiver(args)
        try:
            capture = capture_baseband_notices(
                receiver,
                seconds=args.seconds,
                enable_gate=args.enable_gate,
            )
            notices = capture.notices
        except CommandRejected as error:
            write_json(
                {
                    "status": "receiver_rejected",
                    "command": error.command,
                    "reason": error.response,
                    "notices": [],
                },
                args.json,
            )
            return 2
        finally:
            receiver.close()
    payload = _payload(notices)
    if capture is not None:
        payload["capture"] = capture.manifest()
    print(
        f"Baseband notices: {len(notices)} notices decoded",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
