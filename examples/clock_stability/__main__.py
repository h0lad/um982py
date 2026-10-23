"""Collect a TIME track and report the Allan deviation of the clock offset."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from examples.clock_stability import SLOPE_BLOCKS, ClockStability, analyse
from um982py.capture import capture_records, uniform_interval
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def payload_of(report: ClockStability) -> dict[str, object]:
    """Serialisable view of a stability report."""
    return {
        "sample_count": report.sample_count,
        "taus": list(report.taus),
        "phase_deviation": list(report.phase_deviation),
        "frequency_deviation": list(report.frequency_deviation),
        "phase_slope": report.phase_slope,
        "frequency_slope": report.frequency_slope,
        "noise": None if report.noise is None else report.noise.value,
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.clock_stability",
        description="TIME clock offset stability",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live collection time in seconds"
    )
    parser.add_argument("--frames", type=int, default=600, help="TIME frames to keep")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="TIME output interval in seconds"
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
        print(f"clock_stability debug: records={counts}", file=sys.stderr, flush=True)

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    """Collect TIME frames and report the Allan deviation of the clock offset."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.frames < 2 * SLOPE_BLOCKS:
        parser.error(f"--frames must be at least {2 * SLOPE_BLOCKS}")
    if args.debug:
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"clock_stability debug: {origin}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.TIME],
        duration=args.duration,
        frames=args.frames,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )["TIME"]
    if not records:
        parser.error("capture contains no TIME records")
    invalid = sum(record["clock_status"] not in (0, "VALID") for record in records)
    if invalid or len(records) < 2 * SLOPE_BLOCKS:
        write_json(
            {
                "status": "insufficient_data",
                "sample_count": len(records),
                "invalid_clock_samples": invalid,
                "reason": "valid clock model and at least 128 samples are required",
            },
            args.json,
        )
        return 1
    offsets = [record.real("clock_offset") for record in records][-args.frames :]
    report = analyse(offsets, tau0=uniform_interval(records, args.interval))
    print(
        f"Clock stability: {report.sample_count} samples; noise {report.noise}; "
        f"phase slope {report.phase_slope}; frequency slope {report.frequency_slope}",
        file=sys.stderr,
    )
    for tau, phase, frequency in zip(
        report.taus, report.phase_deviation, report.frequency_deviation, strict=True
    ):
        print(f"  tau {tau:>8.1f} s  adev {phase:.3e} s  adev_y {frequency:.3e}")
    write_json(payload_of(report), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
