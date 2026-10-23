"""Measures time to first fix from the command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from time import monotonic, sleep

from examples.rtk_quality import FixClass, position_type_code, solution_status_code
from examples.ttff_profile import (
    FixEpoch,
    StartKind,
    TtffMeasurement,
    TtffStatistics,
    compare_starts,
    fix_transitions,
    measure,
    repeatability,
)
from um982py.antenna import antenna_log
from um982py.capture import DataLog, open_receiver, read_frames, record_epoch
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout, TransportError
from um982py.experimental import FirmwareLog
from um982py.messages import Message
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.messages.record import Record
from um982py.subscriptions import temporary_subscriptions

INJECTED_RUNS = {
    StartKind.COLD: (44.0, 45.0, 46.0),
    StartKind.WARM: (11.0, 12.0, 13.0),
}
INJECTED_EPOCHS = 90
INJECTED_CADENCE = 1.0


def injected_epochs(
    ttff_seconds: float,
    *,
    cadence: float = INJECTED_CADENCE,
    epochs: int = INJECTED_EPOCHS,
) -> tuple[FixEpoch, ...]:
    """Timeline whose first computed single solution lands on ``ttff_seconds``."""
    solved = [(index * cadence) >= ttff_seconds for index in range(epochs)]
    return tuple(
        FixEpoch(
            seconds=index * cadence,
            solution_status=(
                SolutionStatus.SOL_COMPUTED
                if fixed
                else SolutionStatus.INSUFFICIENT_OBS
            ),
            position_type=PositionType.SINGLE if fixed else PositionType.NONE,
            satellites=9 if fixed else 0,
        )
        for index, fixed in enumerate(solved)
    )


def injected_runs() -> tuple[tuple[tuple[FixEpoch, ...], TtffMeasurement], ...]:
    """Three injected runs per start kind around the documented mean."""
    return tuple(
        (
            timeline,
            measure(timeline, start=start, reset_seconds=0.0),
        )
        for start, values in INJECTED_RUNS.items()
        for timeline in (injected_epochs(ttff) for ttff in values)
    )


def frames_of(frames: Sequence[Message], log: DataLog) -> list[Record]:
    """Decode every frame of a transcript that carries the given firmware log."""
    records = []
    for message in frames:
        for binary in (False, True):
            if log.request(binary=binary).matches(message):
                records.append(log.decode(message))
                break
    return records


def recorded_epochs(
    records: Sequence[Record], *, cadence: float
) -> tuple[FixEpoch, ...]:
    """Number a captured BESTPOS stream at a fixed cadence from the reset."""
    origin = (
        record_epoch(records[0]) if records and records[0].message is not None else None
    )
    return tuple(
        FixEpoch(
            seconds=record_epoch(record) - origin
            if origin is not None
            else index * cadence,
            solution_status=solution_status_code(record),
            position_type=position_type_code(record),
            satellites=record.integer("count_svs"),
        )
        for index, record in enumerate(records)
    )


def replay_run(
    args: argparse.Namespace,
) -> tuple[tuple[FixEpoch, ...], TtffMeasurement]:
    """Measure one run from a captured transcript, one epoch per cadence."""
    frames = read_frames(args.replay)
    timeline = recorded_epochs(
        frames_of(
            frames,
            antenna_log(FirmwareLog.BESTPOS, getattr(args, "antenna", "primary")),
        ),
        cadence=args.cadence,
    )
    return timeline, measure(timeline, start=args.start, reset_seconds=0.0)


def live_run(args: argparse.Namespace) -> tuple[tuple[FixEpoch, ...], TtffMeasurement]:
    """Reconnect after RESET and bound the wait for the first observed fix."""
    position_log = antenna_log(FirmwareLog.BESTPOS, getattr(args, "antenna", "primary"))
    print(
        f"Starting {args.start.value} reset; fix timeout {args.timeout_seconds:g}s...",
        file=sys.stderr,
        flush=True,
    )
    origin = monotonic()
    deadline = origin + args.timeout_seconds
    with open_receiver(args) as control:
        control.send(args.start.reset_command())
    epochs: list[FixEpoch] = []
    while (remaining := deadline - monotonic()) > 0:
        try:
            with open_receiver(args) as receiver:
                receiver.version()
                with temporary_subscriptions(
                    receiver,
                    (
                        position_log.wire_name(),
                        position_log.output(args.cadence),
                    ),
                ):
                    while (remaining := deadline - monotonic()) > 0 and len(
                        epochs
                    ) < args.epochs:
                        try:
                            message = receiver.receive(
                                timeout=min(receiver.timeout, remaining)
                            )
                        except ResponseTimeout:
                            continue
                        if not position_log.request().matches(message):
                            continue
                        record = position_log.decode(message)
                        epoch = FixEpoch(
                            seconds=monotonic() - origin,
                            solution_status=solution_status_code(record),
                            position_type=position_type_code(record),
                            satellites=record.integer("count_svs"),
                        )
                        epochs.append(epoch)
                        if epoch.is_computed and epoch.fix_class is not FixClass.NONE:
                            return tuple(epochs), measure(
                                epochs, start=args.start, reset_seconds=0.0
                            )
            break
        except (TransportError, ResponseTimeout):
            sleep(min(0.2, max(0.0, deadline - monotonic())))
    return tuple(epochs), measure(epochs, start=args.start, reset_seconds=0.0)


def statistics_payload(statistics: TtffStatistics) -> dict[str, object]:
    """Serialise the repeatability of one start kind."""
    return {
        "start": statistics.start,
        "runs": statistics.runs,
        "mean_seconds": statistics.mean_seconds,
        "stddev_seconds": statistics.stddev_seconds,
        "minimum_seconds": statistics.minimum_seconds,
        "maximum_seconds": statistics.maximum_seconds,
        "spread_seconds": statistics.spread_seconds,
    }


def run_payload(
    timeline: Sequence[FixEpoch], run: TtffMeasurement
) -> dict[str, object]:
    """Serialise one run with the fix-class transitions of its timeline."""
    return {
        "start": run.start,
        "target": run.target,
        "reset_seconds": run.reset_seconds,
        "fix_seconds": run.fix_seconds,
        "ttff_seconds": run.ttff,
        "transitions": [
            [str(fix_class), seconds]
            for fix_class, seconds in fix_transitions(timeline)
        ],
    }


def profile_payload(
    pairs: Sequence[tuple[Sequence[FixEpoch], TtffMeasurement]],
) -> dict[str, object]:
    """Serialise every run with the repeatability and start-kind comparison."""
    runs = [run for _, run in pairs]
    statistics = {
        start: repeatability(
            [run for run in runs if run.start is start and run.ttff is not None]
        )
        for start in StartKind
        if any(run.start is start and run.ttff is not None for run in runs)
    }
    comparison = (
        compare_starts(statistics[StartKind.COLD], statistics[StartKind.WARM])
        if len(statistics) == len(StartKind)
        else None
    )
    return {
        "runs": [run_payload(timeline, run) for timeline, run in pairs],
        "failed_runs": sum(run.ttff is None for run in runs),
        "statistics": [statistics_payload(item) for item in statistics.values()],
        "comparison": None
        if comparison is None
        else {
            "cold_seconds": comparison.cold_seconds,
            "warm_seconds": comparison.warm_seconds,
            "difference_seconds": comparison.difference_seconds,
            "documented_order": comparison.documented_order,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Profile the time to first fix live, from a transcript, or on injected runs."""
    parser = ExampleParser(
        prog="python -m examples.ttff_profile",
        description="Time to first fix after a documented RESET",
    )
    add_receiver_arguments(parser)
    parser.set_defaults(port=None)
    parser.add_argument(
        "--start",
        type=StartKind,
        choices=list(StartKind),
        default=StartKind.COLD,
        help="documented start produced by the reset command",
    )
    parser.add_argument("--runs", type=int, default=3, help="runs per start kind")
    parser.add_argument(
        "--epochs", type=int, default=120, help="BESTPOS epochs to accept per run"
    )
    parser.add_argument(
        "--cadence",
        type=float,
        default=1.0,
        help="seconds between captured epochs in a transcript",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="longest wait for a fix before the run is abandoned",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "ttff_profile")
    if args.port is not None:
        pairs = [live_run(args) for _ in range(args.runs)]
    elif args.replay is not None:
        pairs = [replay_run(args)]
    else:
        pairs = list(injected_runs())
    result = profile_payload(pairs)
    result["source"] = (
        "live"
        if args.port is not None
        else "replay"
        if args.replay is not None
        else "synthetic"
    )
    result["timing_reference"] = (
        "reset command send; first observed fix is an upper bound"
        if args.port is not None
        else "first captured epoch; reset time unavailable"
        if args.replay is not None
        else "injected reset at zero"
    )
    print(
        f"TTFF: {len(pairs)} runs, {result['failed_runs']} failed ({result['source']})",
        file=sys.stderr,
    )
    write_json(result, args.json)
    return 1 if result["failed_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(run(main))
