"""Collect RANGE frames and detect carrier-phase cycle slips."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.cycle_slip_detection import (
    SLIP_THRESHOLD_CYCLES,
    Observation,
    common_mode_events,
    detect_slips,
    report,
)
from um982py.capture import capture_records, gps_signals, record_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def read_observations(record: Record, epoch: float) -> tuple[Observation, ...]:
    """First observation per satellite of one RANGE frame."""
    observations = []
    for item, _ in gps_signals(record, [1575.42e6]):
        prn = item.integer("prn")
        observations.append(
            Observation(
                prn=prn,
                epoch=epoch,
                carrier_phase=item.real("carrier_phase"),
                doppler=item.real("doppler"),
            )
        )
    return tuple(observations)


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.cycle_slip_detection",
        description="Cycle slips from Doppler-predicted carrier-phase increments",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=SLIP_THRESHOLD_CYCLES,
        help="slip threshold in cycles",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between collected RANGE frames",
    )
    parser.add_argument(
        "--frames", type=int, default=60, help="number of RANGE frames to collect"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(
            f"cycle_slip_detection debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Run the slip detector against a receiver or a captured transcript."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"cycle_slip_detection debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.RANGE],
        duration=args.duration,
        frames=args.frames,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )["RANGE"]
    if not records:
        parser.error("capture contains no RANGE records")
    observations = [
        observation
        for index, record in enumerate(records)
        for observation in read_observations(record, record_epoch(record))
    ]
    slips = detect_slips(observations, threshold_cycles=args.threshold)
    candidates = common_mode_events(slips)
    payload = {
        "threshold_cycles": args.threshold,
        "slips": [
            {"prn": slip.prn, "epoch": slip.epoch, "cycles": slip.cycles}
            for slip in slips
        ],
        "clock_jump_candidates": [
            {
                "epoch": event.epoch,
                "prns": list(event.prns),
                "median_cycles": event.median_cycles,
            }
            for event in candidates
        ],
        "satellites": [
            {"prn": item.prn, "epochs": list(item.epochs)} for item in report(slips)
        ],
    }
    print(
        f"Cycle slips: {len(slips)} slips in {len(records)} RANGE epochs"
        + (
            f"; {len(candidates)} shared epochs look like receiver clock jumps"
            if candidates
            else ""
        ),
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
