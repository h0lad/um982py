# Capture and audit native baseband notices alongside tracking diagnostics.

import sys
from collections.abc import Sequence
from dataclasses import asdict

from examples._console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from examples._console_capture import open_receiver, selected_log
from examples.baseband_epoch_audit import audit_baseband
from um982py.capture import decode_records
from um982py.commands import Log
from um982py.errors import ProtocolError
from um982py.experimental import (
    AGC_MESSAGE_ID,
    TRACKING_MESSAGE_ID,
    BasebandStream,
    capture_baseband_notices,
    decode_agc_message,
    decode_tracking_message,
    scan_notices,
)
from um982py.messages import Record
from um982py.protocol import StreamDecoder
from um982py.subscriptions import temporary_subscriptions


def _replay_containers(raw: bytes) -> tuple[list[Record], dict[str, object]]:
    stream = BasebandStream()
    packets = stream.feed(raw)
    records = []
    tracking = []
    agc = []
    errors = []
    for packet in packets:
        try:
            messages = packet.messages
        except ProtocolError as error:
            errors.append(f"Container {packet.sequence}: {error}")
            continue
        for index, message in enumerate(messages):
            if message.message_id not in (AGC_MESSAGE_ID, TRACKING_MESSAGE_ID):
                continue
            provenance = {
                "sequence": packet.sequence,
                "measurement_sync_tag": packet.measurement_sync_tag,
                "message_index": index,
            }
            try:
                if message.message_id == AGC_MESSAGE_ID:
                    agc.append(
                        {
                            **provenance,
                            "native_words": decode_agc_message(message).native_words,
                        }
                    )
                    continue
                record = decode_tracking_message(message)
            except ProtocolError as error:
                errors.append(f"Container {packet.sequence}, message {index}: {error}")
                continue
            records.append(record)
            tracking.append(
                {
                    **provenance,
                    "slot_write_mask": record.integer("field_11"),
                    "fields": dict(record),
                }
            )
    return records, {
        "validated_containers": len(packets),
        "tracking_messages": tracking,
        "agc_messages": agc,
        "decoder_errors": errors,
        "discarded_bytes": stream.discarded,
        "pending_bytes": len(stream.pending),
    }


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
    parser.add_argument(
        "--container-input",
        action="store_true",
        help="Read baseband FIFO containers from a replay file",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    if args.container_input and args.replay is None:
        parser.error("--container-input requires --replay")
    debug_header(args, "baseband_epoch_audit")
    log = selected_log(args, Log.PTOBSINFO)
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
    if args.container_input:
        records, details = _replay_containers(raw)
        result = audit_baseband((), records)
        scope = "baseband container file"
    else:
        decoder = StreamDecoder()
        frames = decoder.feed(raw)
        result = audit_baseband(scan_notices(raw), decode_records(frames, log))
        scope = (
            "entire recorded wire file"
            if args.record or args.replay
            else "bounded notice capture"
        )
        details = {
            "decoder_errors": [str(error) for error in decoder.errors],
            "discarded_bytes": decoder.discarded_bytes,
            "pending_bytes": len(decoder.pending),
        }
    usable = (
        bool(details.get("agc_messages"))
        or len(result.native_tag_counts) >= 2
        or any(s.written_frames for s in result.slot_summaries)
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
                "No wrap modulus, counter frequency or notice-to-GNSS epoch "
                "association is assumed. A later channel can overwrite a slot. "
                "The write mask records assignment. Native "
                "units, signal identities and bank-to-antenna mapping remain "
                "unverified."
            ),
            "analysis_scope": scope,
            "capture": manifest,
            **details,
            **asdict(result),
        },
        args.json,
    )
    return 2 if cleanup_failed else 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
