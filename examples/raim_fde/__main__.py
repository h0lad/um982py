"""Runs the residual chi-square RAIM example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path

from examples.azel_crosscheck import galileo_elements
from examples.ephemeris_orbit import orbit_state, state_from_record
from examples.raim_fde import RaimResult, raim_fde
from examples.wls_position import (
    RangeMeasurement,
    geodetic_position_error,
)
from examples.wls_position.__main__ import _gps_l1
from um982py.capture import capture_records, read_frames
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
from um982py.geodesy import geodetic_from_ecef, receiver_ecef, records_from
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

SATELLITE_SYSTEM_SHIFT = 16
SATELLITE_SYSTEM_MASK = 0b111
RESERVED_SYSTEM = 0b111

_EPHEMERIS_LOGS: Mapping[SatelliteSystem, Log] = {
    SatelliteSystem.GPS: Log.GPSEPH,
    SatelliteSystem.GLONASS: Log.GLOEPH,
    SatelliteSystem.GALILEO: Log.GALEPH,
    SatelliteSystem.BEIDOU: Log.BDSEPH,
}


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


def measurements(
    record: Record,
    ephemerides: Mapping[SatelliteSystem, Mapping[int, Record]],
    epoch: float,
) -> tuple[RangeMeasurement, ...]:
    """Build one highest-C/N0 pseudorange per satellite from an ephemeris set."""
    selected: dict[tuple[SatelliteSystem, int], Record] = {}
    for observation in records_from(record, "observations"):
        tracking = observation.integer("tracking_status")
        code = (tracking >> SATELLITE_SYSTEM_SHIFT) & SATELLITE_SYSTEM_MASK
        if code == RESERVED_SYSTEM:
            continue
        system = SatelliteSystem(code)
        prn = observation.integer("prn")
        if prn not in ephemerides.get(system, {}):
            continue
        key = (system, prn)
        current = selected.get(key)
        if current is None or observation.real("cn0") > current.real("cn0"):
            selected[key] = observation
    measurements = []
    for (system, prn), observation in sorted(selected.items()):
        ephemeris = ephemerides[system][prn]
        if system is SatelliteSystem.GALILEO:
            state = orbit_state(
                galileo_elements(ephemeris), epoch - ephemeris.real("toe")
            )
        elif system is SatelliteSystem.GLONASS:
            state = state_from_record(
                ephemeris, epoch - ephemeris.real("e_time") / 1000.0
            )
        else:
            state = state_from_record(ephemeris, epoch - ephemeris.real("toe"))
        measurements.append(
            RangeMeasurement(
                system=system,
                prn=prn,
                x=state.x,
                y=state.y,
                z=state.z,
                pseudorange=observation.real("pseudorange"),
                pseudorange_std=observation.real("pseudorange_std"),
                satellite_clock=state.clock_bias,
            )
        )
    return tuple(measurements)


def _payload(
    result: RaimResult,
    truth: tuple[float, float, float],
    latitude: float,
    longitude: float,
    measurement_count: int,
) -> dict[str, object]:
    error = geodetic_position_error(
        result.solution, latitude, longitude, truth[0], truth[1], truth[2]
    )
    return {
        "integrity_passed": result.integrity_passed,
        "model": "illustrative GPS L1 residual check; not an integrity certification",
        "measurement_count": measurement_count,
        "alarm": result.alarm,
        "test_statistic": result.test_statistic,
        "threshold": result.threshold,
        "excluded": [
            {"system": system.name, "prn": prn} for system, prn in result.excluded
        ],
        "protection_levels": {"hpl": result.hpl, "vpl": result.vpl},
        "error": {"horizontal": error.horizontal, "vertical": error.vertical},
        "position": {
            "x": result.solution.x,
            "y": result.solution.y,
            "z": result.solution.z,
        },
        "clock_bias_seconds": result.solution.clock_bias,
        "converged": result.solution.converged,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run RAIM fault detection and protection levels on one RANGE epoch."""
    parser = ExampleParser(
        prog="python -m examples.raim_fde",
        description="Residual chi-square RAIM FDE with HPL and VPL",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ephemeris",
        type=Path,
        default=None,
        help="captured ephemeris frames for replay",
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
    debug_header(args, "raim_fde")
    if args.replay is None:
        logs: list[Log | FirmwareLog] = [
            FirmwareLog.RANGE,
            FirmwareLog.BESTPOS,
            Log.GPSEPH,
        ]
        captured = capture_records(
            args,
            logs,
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("raim_fde") if args.debug else None,
        )
        range_records, position_records = captured["RANGE"], captured["BESTPOS"]
        ephemeris_frames = [
            record.message
            for record in captured["GPSEPH"]
            if record.message is not None
        ]
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
    if not range_records or not position_records:
        parser.error("a RANGE frame and a BESTPOS/BESTXYZ frame are required")
    range_record = range_records[0]
    if range_record.message is None:
        parser.error("RANGE frame carries no timestamp")
    epoch = epoch_seconds(range_record.message)
    ephemerides = {
        system: {
            (
                record.integer("satid")
                if system is SatelliteSystem.GALILEO
                else record.integer("sloto")
                if system is SatelliteSystem.GLONASS
                else record.integer("prn")
            ): record
            for record in _decode(ephemeris_frames, log)
        }
        for system, log in _EPHEMERIS_LOGS.items()
    }
    position = position_records[0]
    truth = receiver_position(position)
    observations = _gps_l1(
        range_record, dict(ephemerides.get(SatelliteSystem.GPS, {})), epoch
    )
    result = raim_fde(observations, (*truth, 0.0))
    latitude, longitude = (
        (position.real("lat"), position.real("lon"))
        if "lat" in position
        else geodetic_from_ecef(*truth)[:2]
    )
    payload = _payload(result, truth, latitude, longitude, len(observations))
    error = payload["error"]
    if isinstance(error, dict):
        print(
            f"RAIM: {len(observations)} GPS L1 observations; "
            f"alarm={payload['alarm']}; "
            f"horizontal error {error['horizontal']:.3f} m, "
            f"vertical error {error['vertical']:.3f} m",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
