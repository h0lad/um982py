"""Runs the baseband conformance matrix from the command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from time import monotonic

from examples.baseband_conformance import (
    BasebandSnapshot,
    ConformanceRow,
    StateCheck,
    Verdict,
    all_restored,
    conformance_matrix,
    conformance_row,
    probe,
    probe_commands,
    state_check,
)
from um982py.capture import open_receiver
from um982py.commands import queries
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import CommandRejected, ResponseTimeout, UM982Error
from um982py.experimental import (
    BasebandCommand,
    BasebandNotice,
    rf_spi_read,
    scan_notices,
)
from um982py.experimental.capture import RecordingTransport, ascii_fields
from um982py.experimental.diagnostics import log_list
from um982py.receiver import Receiver

ACKNOWLEDGEMENT = scan_notices(b"$UartBinayCMDOK:\r\n")
REJECTION = scan_notices(b"$UartBinayCMDFAIL:\r\n")


def acknowledged(
    commands: Sequence[BasebandCommand],
) -> dict[BasebandCommand, tuple[BasebandNotice, ...]]:
    """Inject the generic baseband acknowledgement for every command."""
    return dict.fromkeys(commands, ACKNOWLEDGEMENT)


def rejected(
    commands: Sequence[BasebandCommand],
) -> dict[BasebandCommand, tuple[BasebandNotice, ...]]:
    """Inject the generic baseband failure notice for every command."""
    return dict.fromkeys(commands, REJECTION)


def attributed(
    notices: Sequence[BasebandNotice],
) -> dict[BasebandCommand, list[BasebandNotice]]:
    """Group captured notices under the commands that publish that family."""
    grouped: dict[BasebandCommand, list[BasebandNotice]] = {}
    for notice in notices:
        for command in BasebandCommand:
            if command.notice == notice.name:
                grouped.setdefault(command, []).append(notice)
    return grouped


def unattributed(notices: Sequence[BasebandNotice]) -> tuple[str, ...]:
    """Notice families that name no single command of the extended set."""
    families = {command.notice for command in BasebandCommand}
    return tuple(
        sorted({notice.name for notice in notices if notice.name not in families})
    )


def live_probe(
    args: argparse.Namespace, receiver: Receiver, command: BasebandCommand
) -> tuple[ConformanceRow, StateCheck]:
    """Send one bare command through BBCMD and snapshot the state around it."""
    deadline = monotonic() + args.duration
    before = _snapshot(receiver, deadline)
    row = _probe(args, receiver, command, deadline)
    after = _snapshot(receiver, deadline)
    return row, state_check(command, before, after)


def _remaining(deadline: float, timeout: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ResponseTimeout("overall duration exceeded")
    return min(remaining, timeout)


def _snapshot(receiver: Receiver, deadline: float) -> BasebandSnapshot:
    configuration = receiver.collect(
        queries.configuration(),
        timeout=_remaining(deadline, receiver.timeout),
        quiet=0.15,
    )
    mode = receiver.execute(
        queries.mode(), timeout=_remaining(deadline, receiver.timeout)
    )
    masks = receiver.collect(
        queries.masks(), timeout=_remaining(deadline, receiver.timeout), quiet=0.15
    )
    logs = receiver.execute(log_list(), timeout=_remaining(deadline, receiver.timeout))
    return BasebandSnapshot(
        tuple(sorted({message.raw for message in configuration})),
        ascii_fields(mode),
        tuple(sorted({ascii_fields(message) for message in masks})),
        logs,
    )


def _probe(
    args: argparse.Namespace,
    receiver: Receiver,
    command: BasebandCommand,
    deadline: float,
) -> ConformanceRow:
    original = receiver.transport
    recording = RecordingTransport(original, 1024 * 1024)
    receiver.transport = recording
    accepted = False
    try:
        try:
            address = getattr(args, "rf_address", None)
            request = (
                rf_spi_read(address)
                if command is BasebandCommand.RFSPIREAD and address is not None
                else probe(command)
            )
            receiver.execute(request, timeout=_remaining(deadline, receiver.timeout))
            accepted = True
        except (CommandRejected, ResponseTimeout):
            pass
        end = min(deadline, monotonic() + args.window_seconds)
        while (remaining := end - monotonic()) > 0 and not recording.limit_reached:
            try:
                receiver.receive(timeout=min(0.05, remaining))
            except ResponseTimeout:
                continue
    finally:
        receiver.transport = original
    notices = scan_notices(bytes(recording.raw))
    return conformance_row(command, notices, application_ack=accepted)


def live_matrix(args: argparse.Namespace) -> dict[str, object]:
    """Probe every selected command on a receiver with a snapshot around each."""
    rows = []
    checks = []
    commands = args.command or probe_commands(
        include_destructive=args.include_destructive
    )
    deadline = monotonic() + args.duration
    reason: str | None = None
    print(
        f"Probing {len(commands)} commands; total budget {args.duration:g}s, "
        f"I/O timeout {args.timeout:g}s. Ctrl-C saves partial results.",
        file=sys.stderr,
        flush=True,
    )
    with open_receiver(args) as receiver:
        try:
            print("Reading initial receiver state...", file=sys.stderr, flush=True)
            before = _snapshot(receiver, deadline)
            for index, command in enumerate(commands, start=1):
                _remaining(deadline, receiver.timeout)
                print(
                    f"[{index}/{len(commands)}] {command.value}...",
                    file=sys.stderr,
                    flush=True,
                )
                row = _probe(args, receiver, command, deadline)
                rows.append(row)
                after = _snapshot(receiver, deadline)
                check = state_check(command, before, after)
                checks.append(check)
                print(
                    f"  {row.verdict.value}; "
                    f"state {'unchanged' if check.identical else 'CHANGED'}",
                    file=sys.stderr,
                    flush=True,
                )
                if not check.identical:
                    reason = (
                        "probe changed receiver state; remaining probes were skipped"
                    )
                    break
                before = after
        except KeyboardInterrupt:
            reason = "interrupted"
        except (UM982Error, OSError) as error:
            reason = str(error)
    result = payload(tuple(rows), tuple(checks), source="live")
    result["complete"] = reason is None and len(rows) == len(commands)
    if reason is not None or len(rows) != len(commands):
        result["status"] = "incomplete"
    result["stopped_reason"] = reason
    result["unchecked_commands"] = [row.command.value for row in rows[len(checks) :]]
    if len(checks) < len(rows):
        result["restore"] = None
    if result["restore"] is False:
        result["status"] = "restoration_failed"
    result["remaining_commands"] = [command.value for command in commands[len(rows) :]]
    if reason is not None:
        print(f"Stopped: {reason}", file=sys.stderr, flush=True)
    return result


def replay_matrix(args: argparse.Namespace) -> dict[str, object]:
    """Classify a captured baseband notice stream by notice family."""
    notices = scan_notices(args.replay.read_bytes())
    result = payload(
        conformance_matrix(attributed(notices)), checks=(), source="replay"
    )
    result["unattributed"] = list(unattributed(notices))
    return result


def injected_matrix() -> dict[str, object]:
    """Self-check of the classification on the two generic reply notices."""
    commands = probe_commands(include_destructive=True)
    return {
        "source": "injected",
        "accepted": [
            row_payload(row) for row in conformance_matrix(acknowledged(commands))
        ],
        "rejected": [
            row_payload(row) for row in conformance_matrix(rejected(commands))
        ],
        "restore": None,
    }


def row_payload(row: ConformanceRow) -> dict[str, object]:
    """Serialise one matrix row."""
    return {
        "command": row.command,
        "side_effect": row.side_effect,
        "verdict": row.verdict,
        "notices": list(row.notices),
        "application_ack": row.application_ack,
        "probe_safe": row.probe_safe,
    }


def payload(
    rows: Sequence[ConformanceRow], checks: Sequence[StateCheck], *, source: str
) -> dict[str, object]:
    """Serialise the matrix, the state checks and the restore verdict."""
    return {
        "status": (
            "insufficient_data"
            if not rows or any(row.verdict == Verdict.NO_REPORT for row in rows)
            else "ok"
        ),
        "source": source,
        "rows": [row_payload(row) for row in rows],
        "checks": [
            {"command": check.command, "changed": list(check.changed)}
            for check in checks
        ],
        "restore": all_restored(checks) if checks else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the conformance matrix live, from a notice capture, or injected."""
    parser = ExampleParser(
        prog="python -m examples.baseband_conformance",
        description="ACK and reject matrix over the baseband commands",
    )
    add_receiver_arguments(parser)
    parser.set_defaults(port=None, timeout=1.0)
    parser.add_argument(
        "--include-destructive",
        action="store_true",
        help="also probe disruptive commands and commands with unverified effects",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=0.25,
        help="seconds to listen for baseband notices after each command",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="total live run budget in seconds, including state queries",
    )
    parser.add_argument(
        "--command",
        action="append",
        type=BasebandCommand,
        choices=list(BasebandCommand),
        help="probe this command, repeating the option to select several",
    )
    parser.add_argument(
        "--rf-address",
        type=int,
        default=None,
        help="use a validated RF read selector with --command RFSPIREAD, "
        "or omit it to test the bare-command syntax",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "baseband_conformance")
    if args.rf_address is not None:
        if args.command != [BasebandCommand.RFSPIREAD]:
            parser.error("--rf-address requires only --command RFSPIREAD")
        try:
            rf_spi_read(args.rf_address)
        except ValueError as error:
            parser.error(str(error))
    allowed = probe_commands(include_destructive=args.include_destructive)
    if args.command and any(command not in allowed for command in args.command):
        parser.error("selected command requires --include-destructive")
    if args.port is not None:
        result = live_matrix(args)
    elif args.replay is not None:
        result = replay_matrix(args)
    else:
        result = injected_matrix()
    write_json(result, args.json)
    print(
        f"Baseband conformance: complete={result.get('complete')}, "
        f"restore={result.get('restore')}",
        file=sys.stderr,
    )
    if result.get("stopped_reason") == "interrupted":
        return 130
    if result.get("complete") is False:
        return 1
    return 1 if result.get("restore") is False else 0


if __name__ == "__main__":
    raise SystemExit(run(main))
