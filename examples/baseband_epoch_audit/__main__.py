"""Capture and audit native baseband notices alongside tracking diagnostics."""

import sys
from collections.abc import Sequence
from dataclasses import asdict

from examples.baseband_epoch_audit import audit_baseband
from um982py.antenna import antenna_log
from um982py.capture import decode_records, open_receiver
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog, capture_baseband_notices, scan_notices
from um982py.protocol import StreamDecoder
from um982py.subscriptions import temporary_subscriptions


def main(argv: Sequence[str] | None = None) -> int:
    """Report observed transitions and native slots from a bounded passive capture."""
    parser = experiment_parser(
        "baseband_epoch_audit", "Baseband counter and tracking-slot audit"
    )
    parser.add_argument(
        "--enable-gate",
        action="store_true",
        help="enable BBMSG2AP for capture, then disable it. The prior state is unknown",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "baseband_epoch_audit")
    log = antenna_log(FirmwareLog.PTOBSINFO, args.antenna)
    manifest = None
    if args.replay is not None:
        raw = args.replay.read_bytes()
    else:
        with (
            open_receiver(args) as receiver,
            temporary_subscriptions(
                receiver,
                (log.wire_name(binary=True), log.output(args.interval, binary=True)),
            ),
        ):
            capture = capture_baseband_notices(
                receiver,
                seconds=args.duration,
                enable_gate=args.enable_gate,
            )
            raw, manifest = capture.raw, capture.manifest()
        if args.record is not None:
            raw = args.record.read_bytes()
    decoder = StreamDecoder()
    frames = decoder.feed(raw)
    result = audit_baseband(scan_notices(raw), decode_records(frames, log))
    usable = len(result.native_tag_counts) >= 2 or any(
        s.written_frames for s in result.slot_summaries
    )
    cleanup_failed = manifest is not None and not manifest["state_restored"]
    print(
        f"Baseband epoch audit: {len(result.native_tag_counts)} native tags; "
        f"usable={usable}; restored={not cleanup_failed}",
        file=sys.stderr,
    )
    write_json(
        {
            "status": "restoration_failed"
            if cleanup_failed
            else "ok"
            if usable
            else "insufficient_diagnostics",
            "limitation": (
                "Tag jumps are observations, not proof of packet loss or receiver "
                "resets, and no wrap modulus, counter frequency or notice-to-GNSS "
                "epoch association is assumed. Slots are overwritten by channels, "
                "not averaged. Written does not mean valid. Native units, signal "
                "identities and bank-to-antenna mapping remain unverified."
            ),
            "analysis_scope": "entire recorded wire file"
            if args.record or args.replay
            else "bounded notice capture",
            "capture": manifest,
            "decoder_errors": [str(error) for error in decoder.errors],
            "discarded_bytes": decoder.discarded_bytes,
            "pending_bytes": len(decoder.pending),
            **asdict(result),
        },
        args.json,
    )
    return 2 if cleanup_failed else 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
