"""Runs the Klobuchar versus TEC example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from examples.ionosphere_tec import Observation
from examples.klobuchar_vs_tec import (
    GPS_L1_HZ,
    KlobucharCoefficients,
    measured_vertical_delay,
    vertical_delay_metres,
)
from um982py.capture import capture_records, gps_signals, read_frames, record_epoch
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
from um982py.geodesy import geodetic_from_ecef
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

L5_HZ = 1176.45e6
GPS_L1_SIGNAL_TYPE = 0
GPS_L5_SIGNAL_TYPE = 14
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


def _position(frames: Sequence[Message]) -> Record | None:
    for log in (FirmwareLog.BESTPOS, FirmwareLog.BESTXYZ):
        records = _decode_firmware(frames, log)
        if records:
            return records[0]
    return None


def gps_pairs(record: Record) -> dict[int, tuple[Observation, Observation]]:
    """L1/L5 observation pair of every dual-frequency GPS satellite."""
    by_prn: dict[int, dict[int, Observation]] = {}
    for observation, frequency in gps_signals(record):
        signal = GPS_L1_SIGNAL_TYPE if frequency == GPS_L1_HZ else GPS_L5_SIGNAL_TYPE
        by_prn.setdefault(observation.integer("prn"), {})[signal] = Observation(
            prn=observation.integer("prn"),
            frequency_hz=(GPS_L1_HZ if signal == GPS_L1_SIGNAL_TYPE else L5_HZ),
            pseudorange=observation.real("pseudorange"),
            carrier_phase=observation.real("carrier_phase"),
        )
    return {
        prn: (signals[GPS_L1_SIGNAL_TYPE], signals[GPS_L5_SIGNAL_TYPE])
        for prn, signals in by_prn.items()
        if GPS_L1_SIGNAL_TYPE in signals and GPS_L5_SIGNAL_TYPE in signals
    }


def _geometry(record: Record) -> dict[int, tuple[float, float]]:
    if record["constellation"] not in (0, "GPS"):
        return {}
    return {
        satellite.integer("prn"): (
            satellite.real("elevation"),
            satellite.real("azimuth"),
        )
        for satellite in record.records("satellites")
    }


def build_payload(
    coefficients: KlobucharCoefficients,
    epoch: float,
    latitude: float,
    longitude: float,
    pairs: dict[int, tuple[Observation, Observation]],
    geometry: dict[int, tuple[float, float]],
) -> dict[str, object]:
    """Render the per-satellite measured and modelled delays as JSON data."""
    delays = []
    for prn in sorted(set(pairs) & set(geometry)):
        elevation, azimuth = geometry[prn]
        measured = measured_vertical_delay(list(pairs[prn]), elevation)
        if measured is None:
            continue
        modelled = vertical_delay_metres(
            coefficients,
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            azimuth=azimuth,
            gps_seconds=epoch,
        )
        delays.append(
            {
                "prn": prn,
                "elevation": elevation,
                "azimuth": azimuth,
                "measured_vertical_delay_metres": measured,
                "model_vertical_delay_metres": modelled,
                "relative_difference": abs(modelled - measured) / measured
                if measured
                else None,
            }
        )
    return {
        "epoch": epoch,
        "latitude": latitude,
        "longitude": longitude,
        "coefficients": {
            "a0": coefficients.a0,
            "a1": coefficients.a1,
            "a2": coefficients.a2,
            "a3": coefficients.a3,
            "b0": coefficients.b0,
            "b1": coefficients.b1,
            "b2": coefficients.b2,
            "b3": coefficients.b3,
        },
        "delays": delays,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Compare the Klobuchar model with dual-frequency vertical delay."""
    parser = ExampleParser(
        prog="python -m examples.klobuchar_vs_tec",
        description="Klobuchar vertical delay against dual-frequency TEC",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ionosphere",
        type=Path,
        default=None,
        help="captured GPSIONA frame for replay",
    )
    parser.add_argument(
        "--satvis",
        type=Path,
        default=None,
        help="captured SATVIS2A frame for replay",
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
    debug_header(args, "klobuchar_vs_tec")
    if args.replay is None:
        captured = capture_records(
            args,
            [FirmwareLog.RANGE, FirmwareLog.SATVIS2, Log.GPSION, FirmwareLog.BESTPOS],
            duration=args.duration,
            interval=args.interval,
            on_progress=progress_printer("klobuchar_vs_tec") if args.debug else None,
        )
        range_records, satellites = captured["RANGE"], captured["SATVIS2"]
        ionosphere, positions = captured["GPSION"], captured["BESTPOS"]
    else:
        range_frames = read_frames(args.replay)
        ionosphere_frames = (
            list(read_frames(args.ionosphere))
            if args.ionosphere is not None
            else list(range_frames)
        )
        satvis_frames = (
            list(read_frames(args.satvis))
            if args.satvis is not None
            else list(range_frames)
        )
        position_frames = (
            read_frames(args.position) if args.position is not None else range_frames
        )
        range_records = _decode_firmware(range_frames, FirmwareLog.RANGE)
        ionosphere = _decode(ionosphere_frames, Log.GPSION)
        satellites = _decode_firmware(satvis_frames, FirmwareLog.SATVIS2)
        position = _position(position_frames)
        positions = (position,) if position is not None else ()
    if not range_records or not ionosphere or not satellites or not positions:
        parser.error("RANGE, GPSION, SATVIS2 and BESTPOS/BESTXYZ frames are required")
    range_record = range_records[0]
    if range_record.message is None:
        parser.error("RANGE frame carries no timestamp")
    position = positions[0]
    if "lat" in position:
        latitude, longitude = position.real("lat"), position.real("lon")
    else:
        latitude, longitude, _ = geodetic_from_ecef(
            position.real("p_x"), position.real("p_y"), position.real("p_z")
        )
    pairs = gps_pairs(range_record)
    epoch = epoch_seconds(range_record.message)
    geometry: dict[int, tuple[float, float]] = {}
    for record in satellites:
        if record.message is None:
            continue
        if abs(record_epoch(record) - record_epoch(range_record)) >= 1e-6:
            continue
        geometry.update(_geometry(record))
    payload = build_payload(
        KlobucharCoefficients.from_record(ionosphere[0]),
        epoch,
        latitude,
        longitude,
        pairs,
        geometry,
    )
    payload["status"] = (
        "comparison_available" if payload["delays"] else "no_synchronized_GPS_pairs"
    )
    payload["measurement"] = "code TEC; receiver/satellite biases are uncalibrated"
    delays = payload["delays"]
    n_delays = len(delays) if isinstance(delays, list) else 0
    print(
        f"Klobuchar vs TEC: {n_delays} satellite comparisons at "
        f"{latitude:.4f}, {longitude:.4f}",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
