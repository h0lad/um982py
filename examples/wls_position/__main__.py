"""Runs the weighted least-squares positioning example from the command line."""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from examples.ephemeris_orbit import EARTH_ROTATION_RATE, state_from_record
from examples.wls_position import (
    PositionSolution,
    RangeMeasurement,
    geodetic_position_error,
    solve_position,
)
from um982py.capture import capture_records, gps_signals, read_frames
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.geodesy import SPEED_OF_LIGHT, geodetic_from_ecef, receiver_ecef
from um982py.messages import (
    AsciiHeader,
    AsciiMessage,
    BinaryHeader,
    BinaryMessage,
    LegacyAsciiHeader,
    LegacyBinaryHeader,
    Message,
    Record,
)
from um982py.messages.enums import SatelliteSystem

GPS_L1_SIGNAL_TYPE = 0
SATELLITE_SYSTEM_SHIFT = 16
SATELLITE_SYSTEM_MASK = 0b111
SIGNAL_TYPE_SHIFT = 21
SIGNAL_TYPE_MASK = 0b11111


def epoch_seconds(message: Message) -> float:
    """Receiver time of week in seconds from a stamped data frame."""
    if not isinstance(message, (AsciiMessage, BinaryMessage)):
        raise ValueError("message carries no timestamp")
    header = message.header
    if isinstance(header, (AsciiHeader, BinaryHeader)):
        return header.milliseconds / 1000.0
    if isinstance(header, LegacyBinaryHeader):
        return int.from_bytes(header.raw[16:20], "little") / 1000.0
    if isinstance(header, LegacyAsciiHeader):
        return float(header.fields[5])
    raise ValueError("message carries no timestamp")


def receiver_position(record: Record) -> tuple[float, float, float]:
    """Observer ECEF from a BESTPOS or BESTXYZ record."""
    return receiver_ecef(record)


def _decode(frames: Sequence[Message], log: Log) -> tuple[Record, ...]:
    decoded: list[Record] = []
    for message in frames:
        with suppress(ProtocolError):
            decoded.append(log.decode(message))
    return tuple(decoded)


def _decode_firmware(frames: Sequence[Message], log: FirmwareLog) -> tuple[Record, ...]:
    decoded: list[Record] = []
    for message in frames:
        with suppress(ProtocolError):
            decoded.append(log.decode(message))
    return tuple(decoded)


def _gps_l1(
    record: Record, ephemerides: dict[int, Record], epoch: float
) -> tuple[RangeMeasurement, ...]:
    selected: dict[int, Record] = {}
    for observation, _ in gps_signals(record, [1575.42e6], phase=False):
        tracking = observation.integer("tracking_status")
        system = (tracking >> SATELLITE_SYSTEM_SHIFT) & SATELLITE_SYSTEM_MASK
        signal = (tracking >> SIGNAL_TYPE_SHIFT) & SIGNAL_TYPE_MASK
        prn = observation.integer("prn")
        if system != SatelliteSystem.GPS or signal != GPS_L1_SIGNAL_TYPE:
            continue
        if prn not in ephemerides:
            continue
        current = selected.get(prn)
        if current is None or observation.real("cn0") > current.real("cn0"):
            selected[prn] = observation
    measurements = []
    for prn, observation in sorted(selected.items()):
        ephemeris = ephemerides[prn]
        travel = observation.real("pseudorange") / SPEED_OF_LIGHT
        state = state_from_record(ephemeris, epoch - travel - ephemeris.real("toe"))
        state = state_from_record(
            ephemeris, epoch - travel - state.clock_bias - ephemeris.real("toe")
        )
        rotation = EARTH_ROTATION_RATE * travel
        rotated_x = math.cos(rotation) * state.x + math.sin(rotation) * state.y
        rotated_y = -math.sin(rotation) * state.x + math.cos(rotation) * state.y
        measurements.append(
            RangeMeasurement(
                system=SatelliteSystem.GPS,
                prn=prn,
                x=rotated_x,
                y=rotated_y,
                z=state.z,
                pseudorange=observation.real("pseudorange"),
                pseudorange_std=observation.real("pseudorange_std"),
                satellite_clock=state.clock_bias,
            )
        )
    return tuple(measurements)


def _solution_payload(
    solution: PositionSolution,
    truth: tuple[float, float, float],
    latitude: float,
    longitude: float,
    measurement_count: int,
) -> dict[str, object]:
    error = geodetic_position_error(
        solution, latitude, longitude, truth[0], truth[1], truth[2]
    )
    return {
        "model": (
            "GPS L1 broadcast solution with transmit-time and Earth-rotation "
            "corrections; atmosphere uncorrected"
        ),
        "measurement_count": measurement_count,
        "position": {
            "x": solution.x,
            "y": solution.y,
            "z": solution.z,
            "clock_bias_seconds": solution.clock_bias,
        },
        "error": {"horizontal": error.horizontal, "vertical": error.vertical},
        "iterations": solution.iterations,
        "converged": solution.converged,
        "residual_norms": list(solution.residual_norms),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Solve one weighted least-squares epoch against a BESTPOS position."""
    parser = ExampleParser(
        prog="python -m examples.wls_position",
        description="Weighted least-squares single-point positioning from RANGE",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ephemeris",
        type=Path,
        default=None,
        help="captured GPSEPH frames for replay",
    )
    parser.add_argument(
        "--position",
        type=Path,
        default=None,
        help="captured BESTPOS or BESTXYZ frame for replay",
    )
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "wls_position")
    if args.replay is None:
        captured = capture_records(
            args,
            [FirmwareLog.RANGE, FirmwareLog.BESTPOS, Log.GPSEPH],
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("wls_position") if args.debug else None,
        )
        range_records, position_records = captured["RANGE"], captured["BESTPOS"]
        ephemeris_records = captured["GPSEPH"]
    else:
        range_frames = read_frames(args.replay)
        position_frames = (
            read_frames(args.position) if args.position is not None else range_frames
        )
        ephemeris_frames = (
            list(read_frames(args.ephemeris))
            if args.ephemeris is not None
            else list(range_frames)
        )
        range_records = _decode_firmware(range_frames, FirmwareLog.RANGE)
        position_records = _decode_firmware(position_frames, FirmwareLog.BESTPOS)
        if not position_records:
            position_records = _decode_firmware(position_frames, FirmwareLog.BESTXYZ)
        ephemeris_records = _decode(ephemeris_frames, Log.GPSEPH)
    if not range_records or not position_records:
        parser.error("a RANGE frame and a BESTPOS/BESTXYZ frame are required")
    range_record = range_records[0]
    if range_record.message is None:
        parser.error("RANGE frame carries no timestamp")
    epoch = epoch_seconds(range_record.message)
    ephemerides = {record.integer("prn"): record for record in ephemeris_records}
    measurements = _gps_l1(range_record, ephemerides, epoch)
    if not measurements:
        parser.error("no GPS L1 observations have a matching ephemeris")
    position = position_records[0]
    truth = receiver_position(position)
    solution = solve_position(measurements, (*truth, 0.0))
    latitude, longitude = (
        (position.real("lat"), position.real("lon"))
        if "lat" in position
        else geodetic_from_ecef(*truth)[:2]
    )
    payload = _solution_payload(solution, truth, latitude, longitude, len(measurements))
    error = payload["error"]
    if isinstance(error, dict):
        print(
            f"WLS position: {len(measurements)} GPS L1 ranges; "
            f"horizontal error {error['horizontal']:.3f} m, "
            f"vertical error {error['vertical']:.3f} m; "
            f"converged={payload['converged']}",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
