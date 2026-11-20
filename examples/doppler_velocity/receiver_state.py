"""Record the receiver's Doppler velocity and compare its ECEF reports."""

import sys
from collections.abc import Iterable, Iterator, Sequence
from math import dist, isfinite
from time import monotonic

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import open_receiver
from um982py.capture import iter_frames, record_epoch
from um982py.commands import Log
from um982py.errors import ResponseTimeout
from um982py.experimental import VelocityData, velocity_data_output, velocity_data_read
from um982py.messages import Message, Record
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.receiver import Receiver
from um982py.subscriptions import temporary_subscriptions


def _live_frames(receiver: Receiver, duration: float) -> Iterator[Message]:
    deadline = monotonic() + duration
    while (remaining := deadline - monotonic()) > 0:
        try:
            yield receiver.receive(timeout=min(remaining, receiver.timeout))
        except ResponseTimeout:
            continue


def _report(frames: Iterable[Message]) -> dict[str, object]:
    native_request = velocity_data_read()
    reference_request = Log.BESTNAVXYZ.read(binary=True)
    native: dict[float, VelocityData] = {}
    reference: dict[float, Record] = {}
    for frame in frames:
        if native_request.matches(frame):
            sample = native_request.decode(frame)
            native[sample.epoch_gps_seconds] = sample
        elif reference_request.matches(frame):
            record = reference_request.decode(frame)
            if (
                record.get("v_sol_status") == SolutionStatus.SOL_COMPUTED
                and record.get("vel_type") == PositionType.DOPPLER_VELOCITY
            ):
                reference[record_epoch(record)] = record

    velocity_errors = []
    uncertainty_errors = []
    epochs = []
    for epoch, sample in sorted(native.items()):
        comparison = None
        standard = reference.get(epoch)
        if standard is not None and sample.velocity_std_ecef_mps is not None:
            velocity = tuple(standard.real(field) for field in ("v_x", "v_y", "v_z"))
            deviations = tuple(
                standard.real(field) for field in ("v_x_std", "v_y_std", "v_z_std")
            )
            if all(map(isfinite, velocity)) and all(
                isfinite(value) and value >= 0 for value in deviations
            ):
                velocity_difference = dist(sample.velocity_ecef_mps, velocity)
                axis_differences = tuple(
                    abs(left - right)
                    for left, right in zip(
                        sample.velocity_std_ecef_mps, deviations, strict=True
                    )
                )
                velocity_errors.append(velocity_difference)
                uncertainty_errors.append(max(axis_differences))
                comparison = {
                    "velocity_difference_mps": velocity_difference,
                    "axis_std_differences_mps": axis_differences,
                }
        epochs.append(
            {
                "gps_seconds": epoch,
                "velocity_ecef_mps": sample.velocity_ecef_mps,
                "velocity_std_ecef_mps": sample.velocity_std_ecef_mps,
                "uncertainty_3d_mps": sample.uncertainty_3d_mps,
                "clock_drift_mps": sample.clock_drift_mps,
                "bestnavxyz_comparison": comparison,
            }
        )
    return {
        "status": "ok" if native else "insufficient_data",
        "matched_epochs": len(velocity_errors),
        "max_velocity_difference_mps": max(velocity_errors, default=None),
        "max_axis_std_difference_mps": max(uncertainty_errors, default=None),
        "epochs": epochs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect or replay primary-antenna VELDATAB and BESTNAVXYZB reports."""
    parser = ExampleParser(
        prog="python -m examples.doppler_velocity.receiver_state",
        description="Inspect native Doppler velocity, uncertainty and clock drift",
    )
    add_receiver_arguments(parser, antenna=False)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live capture seconds"
    )
    parser.add_output_interval()
    args = parser.parse_args(argv)
    if args.replay is not None:
        report = _report(iter_frames(args.replay))
    else:
        reference = Log.BESTNAVXYZ.wire_name(binary=True)
        with (
            open_receiver(args) as receiver,
            temporary_subscriptions(
                receiver,
                (velocity_data_read().text, velocity_data_output(args.interval)),
                (reference, Log.BESTNAVXYZ.output(args.interval, binary=True)),
            ),
        ):
            report = _report(_live_frames(receiver, args.duration))
    write_json(report, args.json)
    print(f"Matched {report['matched_epochs']} BESTNAVXYZ epochs", file=sys.stderr)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
