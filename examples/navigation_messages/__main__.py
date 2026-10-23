"""Runs the navigation message figures from the command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from examples.ephemeris_orbit import receiver_ecef
from examples.navigation_messages import (
    FAMILIES,
    figures,
    navigation_satellites,
    satellite_csv,
    satellite_payload,
)
from um982py import Receiver
from um982py.antenna import antenna_log
from um982py.capture import open_receiver, read_frames
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout
from um982py.experimental import FirmwareLog
from um982py.geodesy import ecef_from_geodetic
from um982py.messages import Record

POSITION_LOGS: tuple[FirmwareLog, ...] = (FirmwareLog.BESTPOS, FirmwareLog.BESTXYZ)


def _records(paths: Sequence[Path], name: str) -> tuple[Record, ...]:
    """Decode one ephemeris family from every transcript given."""
    log = Log(name)
    decoded = []
    for path in paths:
        for message in read_frames(path):
            for binary in (True, False):
                if log.request(binary=binary).matches(message):
                    decoded.append(log.decode(message))
                    break
    return tuple(decoded)


def _position(
    paths: Sequence[Path], antenna: str = "primary"
) -> tuple[float, float, float] | None:
    """Observer ECEF from the first BESTPOS or BESTXYZ record of a capture."""
    for source in POSITION_LOGS:
        log = antenna_log(source, antenna)
        for path in paths:
            for message in read_frames(path):
                for binary in (True, False):
                    if log.request(binary=binary).matches(message):
                        return receiver_ecef(log.decode(message))
    return None


def _transcript_records(paths: Sequence[Path]) -> dict[str, tuple[Record, ...]]:
    """Decode all four ephemeris families from captured transcripts."""
    return {name: _records(paths, name) for name in FAMILIES}


def _observed_records(
    receiver: Receiver, seconds: float
) -> dict[str, tuple[Record, ...]]:
    """Request all four ephemeris families from the receiver."""
    collected = {}
    for name in FAMILIES:
        print(f"Querying {name} (up to {seconds:g}s)...", file=sys.stderr, flush=True)
        try:
            collected[name] = receiver.collect(Log(name).read(), timeout=seconds)
        except ResponseTimeout:
            collected[name] = ()
    return collected


def _device_position(
    receiver: Receiver, antenna: str = "primary"
) -> tuple[float, float, float] | None:
    """Observer ECEF from the receiver's own BESTPOS record."""
    try:
        positions = receiver.collect(antenna_log(FirmwareLog.BESTPOS, antenna).read())
    except ResponseTimeout:
        return None
    return receiver_ecef(positions[-1]) if positions else None


def _newest_epoch(records: dict[str, tuple[Record, ...]]) -> float:
    """Newest broadcast reference epoch, in seconds of the GPS week."""
    return max(
        record.real("e_time") / 1000.0 if "e_time" in record else record.real("toe")
        for family in records.values()
        for record in family
    )


def _observer(text: str) -> tuple[float, float, float]:
    """Parse a ``lat,lon,height`` observer argument."""
    try:
        values = [float(part) for part in text.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if len(values) != 3:
        raise argparse.ArgumentTypeError("observer must be lat,lon,height")
    return values[0], values[1], values[2]


def _replayed(
    paths: Sequence[Path],
    antenna: str = "primary",
) -> tuple[dict[str, tuple[Record, ...]], tuple[float, float, float] | None]:
    """Ephemerides and observer position of captured transcripts."""
    return _transcript_records(paths), _position(paths, antenna)


def main(argv: Sequence[str] | None = None) -> int:
    """Collect or replay navigation messages, then write the three figures."""
    parser = ExampleParser(
        prog="python -m examples.navigation_messages", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--transcripts",
        type=Path,
        default=None,
        help="directory of captured transcripts to replay",
    )
    parser.add_argument(
        "--output", type=Path, default=Path(), help="directory for the figures"
    )
    parser.add_argument(
        "--observer",
        type=_observer,
        default=None,
        help="observer lat,lon,height in degrees and metres",
    )
    parser.add_argument(
        "--epoch",
        type=float,
        default=None,
        help="reference GPS time of week in seconds for the propagation",
    )
    parser.add_argument(
        "--seconds", type=float, default=5.0, help="collection time in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "navigation_messages")
    if args.replay is not None:
        records, observer = _replayed([Path(args.replay)], args.antenna)
    elif args.transcripts is not None:
        records, observer = _replayed(
            sorted(Path(args.transcripts).glob("*.bin")), args.antenna
        )
    else:
        receiver = open_receiver(args)
        try:
            records = _observed_records(receiver, args.seconds)
            observer = _device_position(receiver, getattr(args, "antenna", "primary"))
        finally:
            receiver.close()
    if args.observer is not None:
        observer = ecef_from_geodetic(*args.observer)
    if observer is None:
        parser.error("no BESTPOS or BESTXYZ record to place the satellites from")
    if not any(records.values()):
        parser.error("capture contains no broadcast ephemerides")
    epoch = _newest_epoch(records) if args.epoch is None else args.epoch
    satellites = navigation_satellites(records, observer, epoch)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, document in figures(satellites).items():
        (args.output / name).write_text(document)
    (args.output / "satellites.csv").write_text(satellite_csv(satellites))
    print(
        f"Navigation messages: {len(satellites)} satellites propagated "
        f"to epoch {epoch:g}",
        file=sys.stderr,
    )
    write_json(satellite_payload(satellites), args.json)
    return 0 if satellites else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
