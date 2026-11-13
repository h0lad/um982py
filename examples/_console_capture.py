"""Command-line adapters for opening a receiver and collecting logs."""

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

from um982py.antenna import antenna_log, swap_antenna
from um982py.augmentation import enable_augmentation
from um982py.capture import (
    DataLog,
    InterruptedCapture,
    RecordingTransport,
    capture_live,
    iter_frames,
    replay_receiver,
)
from um982py.commands.configuration import ppp, ppp_datum
from um982py.messages import Record
from um982py.receiver import Receiver
from um982py.stream_capture import iter_decoded_records


def open_receiver(args: argparse.Namespace) -> Receiver:
    """Open the device, or replay a captured transcript."""
    replay = getattr(args, "replay", None)
    if replay is not None:
        return replay_receiver(Path(replay).read_bytes())
    receiver = Receiver.connect(
        args.port, args.baud, timeout=getattr(args, "timeout", 3.0)
    )
    with ExitStack() as cleanup:
        cleanup.callback(receiver.close)
        if getattr(args, "augment", False):
            state = enable_augmentation(receiver)
            if state.changed and state.active_group is not None:
                print(
                    "augmentation: signal group "
                    f"{state.previous_group.master} "
                    f"{state.previous_group.slave} -> "
                    f"{state.active_group.master} {state.active_group.slave}; "
                    "SBAS, E6-HAS, B2b-PPP and MMP asserted",
                    file=sys.stderr,
                )
            refused = ", ".join(name for name, _ in state.rejected)
            if refused:
                print(f"augmentation refused: {refused}", file=sys.stderr)
        service = getattr(args, "ppp_service", None)
        if service in ("AUTO", "E6-HAS", "B2B-PPP"):
            receiver.execute(ppp(enabled=True, service=service))
            receiver.execute(ppp_datum("WGS84"))
            print(f"PPP service: {service}, datum WGS84", file=sys.stderr)
        destination = getattr(args, "record", None)
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            stream = destination.open(
                "ab" if getattr(args, "_record_started", False) else "xb"
            )
            receiver.transport = RecordingTransport(receiver.transport, stream)
            args._record_started = True
        cleanup.pop_all()
        return receiver


def capture_records(
    args: argparse.Namespace,
    logs: Sequence[DataLog],
    *,
    frames: int | None = None,
    interval: float = 1.0,
    duration: float | None = None,
    binary: bool = True,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
) -> dict[str, tuple[Record, ...]]:
    """Replay a file directly or temporarily stream all requested logs together."""
    antenna = getattr(args, "antenna", "primary")
    if getattr(args, "swap_antennas", False):
        logs = [swap_antenna(antenna_log(log, antenna)) for log in logs]
    else:
        logs = [antenna_log(log, antenna) for log in logs]
    if frames is not None and frames < 1:
        raise ValueError("frames must be positive")
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval must be positive")
    if args.replay is not None:
        collected: dict[str, list[Record]] = {log.value: [] for log in logs}
        for name, record in iter_decoded_records(
            iter_frames(args.replay), logs, max_records_per_log=frames
        ):
            collected[name].append(record)
            if arrival_order is not None:
                arrival_order.append(record)
        result = {name: tuple(values) for name, values in collected.items()}
        if on_progress is not None:
            on_progress(result)
        return result
    seconds = (
        duration
        if duration is not None
        else (frames * interval + args.timeout if frames is not None else 3.0)
    )
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("capture duration must be positive")
    print(
        f"Collecting {', '.join(log.wire_name(binary=False) for log in logs)} "
        f"for up to {seconds:g}s (antenna {getattr(args, 'antenna', 'primary')})...",
        file=sys.stderr,
        flush=True,
    )
    with open_receiver(args) as receiver:
        try:
            result = capture_live(
                receiver,
                logs,
                duration=seconds,
                frames=frames,
                interval=interval,
                binary=binary,
                arrival_order=arrival_order,
                on_progress=on_progress,
                show_progress=True,
            )
        except InterruptedCapture as interrupted:
            result = interrupted.records
    if on_progress is not None:
        on_progress(result)
    print(
        "Collected "
        + ", ".join(f"{name}: {len(values)}" for name, values in result.items()),
        file=sys.stderr,
        flush=True,
    )
    return result


def capture_logs(
    args: argparse.Namespace,
    logs: Sequence[DataLog],
    *,
    arrival_order: list[Record] | None = None,
    on_progress: Callable[[dict[str, tuple[Record, ...]]], None] | None = None,
) -> dict[str, tuple[Record, ...]]:
    """Capture or replay all requested logs using command-line options."""
    return capture_records(
        args,
        logs,
        duration=args.duration,
        interval=args.interval,
        arrival_order=arrival_order,
        on_progress=on_progress,
    )
