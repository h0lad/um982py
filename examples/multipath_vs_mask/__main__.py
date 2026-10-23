"""Sweeps elevation masks for multipath from the command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from examples.multipath_analysis import Observation
from examples.multipath_vs_mask import (
    CARRIER_HZ,
    ZENITH_MULTIPATH_METRES,
    MaskStep,
    ReceiverState,
    SkySignal,
    elevated_series,
    is_falling,
    mask_degrees,
    mask_step,
    mask_sweep,
    synthetic_observations,
    verify_restore,
)
from um982py.antenna import antenna_log
from um982py.capture import (
    GPS_FREQUENCIES,
    DataLog,
    gps_signals,
    open_receiver,
    read_frames,
    receive_records,
    record_epoch,
)
from um982py.commands.configuration import elevation_mask
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.experimental.capture import receiver_state
from um982py.messages import Message
from um982py.messages.record import Record
from um982py.subscriptions import temporary_subscriptions

DEFAULT_MASKS = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
DEFAULT_ELEVATIONS = (
    (5, 8.0),
    (16, 17.0),
    (18, 27.0),
    (26, 38.0),
    (27, 52.0),
    (29, 68.0),
    (31, 82.0),
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


def observations_from(
    records: Sequence[Record], *, interval: float, frequency_hz: float
) -> tuple[Observation, ...]:
    """First observation per satellite of every collected RANGE frame."""
    observations = []
    for record in records:
        seen = set()
        for observation, _ in gps_signals(record, [frequency_hz]):
            prn = observation.integer("prn")
            if prn in seen:
                continue
            seen.add(prn)
            observations.append(
                Observation(
                    prn=prn,
                    epoch=record_epoch(record),
                    frequency_hz=frequency_hz,
                    pseudorange=observation.real("pseudorange"),
                    carrier_phase=observation.real("carrier_phase"),
                )
            )
    return tuple(observations)


def gps_elevations(records: Sequence[Record]) -> dict[int, float]:
    """Minimum GPS elevation across the capture, keeping constellation identity."""
    elevations: dict[int, float] = {}
    for record in records:
        if record["constellation"] not in (0, "GPS"):
            continue
        for satellite in record.records("satellites"):
            prn, elevation = satellite.integer("prn"), satellite.real("elevation")
            elevations[prn] = min(elevations.get(prn, elevation), elevation)
    return elevations


def payload(
    steps: Sequence[MaskStep],
    *,
    restore: tuple[bool, tuple[str, ...]] | None,
) -> dict[str, object]:
    """Serialise the sweep steps, the monotonicity verdict and the restore check."""
    return {
        "masks": [step.mask_degrees for step in steps],
        "steps": [
            {
                "mask_degrees": step.mask_degrees,
                "signals": step.signals,
                "rms": step.rms,
            }
            for step in steps
        ],
        "falling": is_falling(steps),
        "restore": None
        if restore is None
        else {"identical": restore[0], "changed": list(restore[1])},
    }


def live_sweep(args: argparse.Namespace) -> dict[str, object]:
    """Sweep the mask on a receiver and restore the captured mask afterwards."""
    range_log = antenna_log(FirmwareLog.RANGE, getattr(args, "antenna", "primary"))
    with open_receiver(args) as receiver:
        before = ReceiverState.from_parts(receiver_state(receiver))
        original = mask_degrees(before)
        steps = []
        with temporary_subscriptions(
            receiver,
            (
                range_log.wire_name(binary=True),
                range_log.output(args.interval, binary=True),
            ),
            (
                FirmwareLog.SATVIS2.wire_name(binary=True),
                FirmwareLog.SATVIS2.output(args.interval, binary=True),
            ),
        ):
            try:
                for mask in sorted(args.masks):
                    receiver.execute(elevation_mask(mask))
                    print(
                        f"Mask {mask:g} degrees: collecting {args.frames} epochs...",
                        file=sys.stderr,
                        flush=True,
                    )
                    captured = receive_records(
                        receiver,
                        [range_log, FirmwareLog.SATVIS2],
                        duration=args.frames * args.interval + args.timeout,
                        show_progress=True,
                    )
                    frames, sky = captured["RANGE"], captured["SATVIS2"]
                    observations = observations_from(
                        frames[: args.frames],
                        interval=args.interval,
                        frequency_hz=args.frequency,
                    )
                    steps.append(
                        mask_step(
                            mask,
                            elevated_series(observations, gps_elevations(sky)),
                        )
                    )
            finally:
                receiver.execute(elevation_mask(original))
        after = ReceiverState.from_parts(receiver_state(receiver))
    report = verify_restore(before, after)
    return payload(steps, restore=(report.identical, report.changed))


def replay_sweep(args: argparse.Namespace) -> dict[str, object]:
    """Replay one captured pass at every mask without re-measuring it."""
    frames = read_frames(args.replay)
    observations = observations_from(
        frames_of(
            frames, antenna_log(FirmwareLog.RANGE, getattr(args, "antenna", "primary"))
        ),
        interval=args.interval,
        frequency_hz=args.frequency,
    )
    elevations = gps_elevations(frames_of(frames, FirmwareLog.SATVIS2))
    series = elevated_series(observations, elevations)
    return payload(mask_sweep(series, args.masks), restore=None)


def injected_sweep(args: argparse.Namespace) -> dict[str, object]:
    """Sweep the masks over the injected inverse-sine multipath model."""
    signals = tuple(
        SkySignal.at_elevation(prn, elevation, zenith_amplitude=args.zenith_amplitude)
        for prn, elevation in DEFAULT_ELEVATIONS
    )
    observations = synthetic_observations(
        signals, period=args.period, samples=args.samples
    )
    elevations = {signal.prn: signal.elevation for signal in signals}
    series = elevated_series(observations, elevations)
    return payload(mask_sweep(series, args.masks), restore=None)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mask sweep live, from a transcript, or over the injected model."""
    parser = ExampleParser(
        prog="python -m examples.multipath_vs_mask",
        description="Elevation-mask sweep of code-minus-carrier multipath",
    )
    add_receiver_arguments(parser)
    parser.set_defaults(port=None)
    parser.add_argument(
        "--masks",
        type=float,
        nargs="+",
        default=list(DEFAULT_MASKS),
        help="elevation masks in degrees, swept in ascending order",
    )
    parser.add_argument(
        "--frames", type=int, default=60, help="number of RANGE frames per mask"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="seconds between RANGE frames"
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=CARRIER_HZ,
        choices=tuple(GPS_FREQUENCIES.values()),
        help="carrier frequency of the observations in Hz",
    )
    parser.add_argument(
        "--period",
        type=float,
        default=60.0,
        help="injected multipath period in seconds",
    )
    parser.add_argument(
        "--samples", type=int, default=120, help="injected samples per satellite"
    )
    parser.add_argument(
        "--zenith-amplitude",
        type=float,
        default=ZENITH_MULTIPATH_METRES,
        help="injected multipath amplitude at zenith in metres",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "multipath_vs_mask")
    if args.port is not None:
        result = live_sweep(args)
    elif args.replay is not None:
        result = replay_sweep(args)
    else:
        result = injected_sweep(args)
    result["source"] = (
        "live"
        if args.port is not None
        else "replay"
        if args.replay is not None
        else "synthetic"
    )
    steps = result.get("steps")
    print(
        f"Multipath vs mask: "
        f"{len(steps) if isinstance(steps, list) else 0} mask steps "
        f"({result['source']})",
        file=sys.stderr,
    )
    write_json(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
