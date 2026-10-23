"""Dump every received navigation message as annotated hexadecimal."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from math import isfinite
from time import monotonic

from examples.navigation_message_hex import (
    MessageHex,
    families,
    message_hex,
    render_text,
)
from um982py import Receiver
from um982py.antenna import AntennaLog, antenna_log
from um982py.capture import open_receiver, read_frames
from um982py.commands import Log, Trigger
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import CommandRejected, ResponseTimeout
from um982py.experimental import FirmwareLog
from um982py.messages import BinaryMessage, Message
from um982py.subscriptions import temporary_subscriptions

__all__ = ["main"]


def resolve(name: str) -> Log | FirmwareLog:
    """Documented or extended log by name."""
    if name in Log.__members__:
        return Log[name]
    try:
        return FirmwareLog[name]
    except KeyError as error:
        raise ValueError(f"Unknown log: {name}") from error


def _targets(
    wanted: Sequence[str], extra: Sequence[str], antenna: str = "primary"
) -> tuple[tuple[str, Log | FirmwareLog], ...]:
    unknown = set(wanted) - dict(families()).keys()
    if unknown:
        raise ValueError(f"Unknown families: {', '.join(sorted(unknown))}")
    names = [(name, log) for name, log in families() if not wanted or name in wanted]
    names.extend((name, name) for name in extra)
    targets: dict[str, tuple[str, Log | FirmwareLog]] = {}
    for constellation, log_name in names:
        selected = antenna_log(resolve(log_name), antenna)
        log = selected.wire if isinstance(selected, AntennaLog) else selected
        log.request(binary=True)
        targets.setdefault(log.value, (constellation, log))
    return tuple(targets.values())


def _annotate(
    message: Message, targets: Sequence[tuple[str, Log | FirmwareLog]]
) -> MessageHex | None:
    if isinstance(message, BinaryMessage):
        for constellation, log in targets:
            if log.request(binary=True).matches(message):
                return message_hex(
                    constellation,
                    log.value,
                    message.header.message_id,
                    message.payload,
                    log.decode(message),
                )
    return None


def replay(
    frames: Iterable[Message],
    wanted: Sequence[str],
    extra: Sequence[str] = (),
    antenna: str = "primary",
) -> list[MessageHex]:
    """Annotate matching captured frames without changing receiver state."""
    targets = _targets(wanted, extra, antenna)
    return [view for frame in frames if (view := _annotate(frame, targets)) is not None]


def collect(
    receiver: Receiver,
    seconds: float,
    wanted: Sequence[str],
    extra: Sequence[str] = (),
    antenna: str = "primary",
) -> list[MessageHex]:
    """Subscribe the requested binary logs and annotate every frame."""
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be finite and positive")
    targets = _targets(wanted, extra, antenna)
    messages: list[MessageHex] = []
    with ExitStack() as subscriptions:
        for _, log in targets:
            wire = log.wire_name(binary=True)
            try:
                subscriptions.enter_context(
                    temporary_subscriptions(
                        receiver, (wire, log.output(Trigger.ON_CHANGED, binary=True))
                    )
                )
            except (ValueError, CommandRejected):
                subscriptions.enter_context(
                    temporary_subscriptions(
                        receiver, (wire, log.output(1, binary=True))
                    )
                )
        deadline = monotonic() + seconds
        while (remaining := deadline - monotonic()) > 0:
            try:
                message = receiver.receive(timeout=min(0.5, remaining))
            except ResponseTimeout:
                continue
            view = _annotate(message, targets)
            if view is not None:
                messages.append(view)
    return messages


def payload(messages: Sequence[MessageHex]) -> dict[str, object]:
    """Machine-readable form of the annotated messages."""
    return {
        "messages": [
            {
                "constellation": message.constellation,
                "log": message.log,
                "message_id": message.message_id,
                "satellite": message.satellite,
                "bytes": len(message.payload),
                "hex": message.hex,
                "fields": [
                    {
                        "name": field.name,
                        "offset": field.offset,
                        "size": field.size,
                        "hex": field.hex,
                        "value": field.value,
                    }
                    for field in message.fields
                ],
            }
            for message in messages
        ]
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print the raw navigation messages of every visible constellation."""
    parser = ExampleParser(
        prog="python -m examples.navigation_message_hex", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="restrict to a constellation, repeating the option to select several",
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        dest="extra",
        help="also dump any other binary log by name, for example ENVINFO",
    )
    args = parser.parse_args(argv)
    debug_header(args, "navigation_message_hex")
    if not isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be finite and positive")
    try:
        _targets(args.family, args.extra, args.antenna)
    except ValueError as error:
        parser.error(str(error))
    if args.replay is not None:
        messages = replay(
            read_frames(args.replay), args.family, args.extra, args.antenna
        )
    else:
        with open_receiver(args) as receiver:
            messages = collect(
                receiver, args.seconds, args.family, args.extra, args.antenna
            )
    if messages:
        text = "\n\n".join(render_text(message) for message in messages)
        print(text)
    print(
        f"Nav hex: {len(messages)} annotated messages",
        file=sys.stderr,
    )
    write_json(payload(messages), args.json)
    return 0 if messages else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
