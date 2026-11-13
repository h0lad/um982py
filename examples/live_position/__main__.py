"""Print GGA positions and reconnect when the receiver disconnects."""

import argparse
import json
from collections.abc import Sequence
from contextlib import closing
from threading import Event

from um982py import (
    LiveLimits,
    PositionMonitor,
    PositionSession,
    Receiver,
    geojson_feature,
)
from um982py.commands import Log


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="serial port or tcp://host:port")
    parser.add_argument("--baud", type=int, default=115200)
    rate = parser.add_mutually_exclusive_group()
    rate.add_argument("--interval", type=float, help="GGA output interval in seconds")
    rate.add_argument("--rate-hz", type=float, help="GGA output rate in Hz")
    parser.add_argument(
        "--geojson", action="store_true", help="output WGS84 fixes as GeoJSON lines"
    )
    parser.add_argument(
        "--max-gap", type=float, help="maximum arrival interval in seconds"
    )
    parser.add_argument(
        "--max-correction-age", type=float, help="maximum correction age in seconds"
    )
    args = parser.parse_args(argv)
    try:
        command = Log.GPGGA.output(args.interval, rate_hz=args.rate_hz)
    except ValueError as error:
        parser.error(str(error))

    def configure(receiver: Receiver) -> None:
        receiver.execute(command)

    session = PositionSession(
        lambda: Receiver.connect(args.target, args.baud), configure=configure
    )
    monitor = PositionMonitor(
        LiveLimits(max_gap_s=args.max_gap, max_correction_age_s=args.max_correction_age)
    )
    try:
        with closing(session.positions(Event())) as positions:
            for update in positions:
                fix = update.fix
                assessment = monitor.observe(update)
                if args.geojson:
                    feature = geojson_feature(update, reference_frame="WGS84")
                    if feature is not None:
                        feature["properties"]["assessment_reasons"] = assessment.reasons
                        print(json.dumps(feature, allow_nan=False), flush=True)
                    continue
                print(
                    f"{update.received_at.isoformat()} quality={fix.quality} "
                    f"lat={fix.latitude} lon={fix.longitude} "
                    f"height_msl={fix.altitude_msl} "
                    f"correction_age={fix.correction_age_s} "
                    f"connection={update.connection} reasons={assessment.reasons}",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
