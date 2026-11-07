"""Print GGA positions and reconnect when the receiver disconnects."""

import argparse
from collections.abc import Sequence
from contextlib import closing
from threading import Event

from um982py import LiveLimits, PositionMonitor, PositionSession, Receiver
from um982py.commands import Log


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="serial port or tcp://host:port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--max-gap", type=float, help="maximum arrival interval in seconds"
    )
    parser.add_argument(
        "--max-correction-age", type=float, help="maximum correction age in seconds"
    )
    args = parser.parse_args(argv)

    def configure(receiver: Receiver) -> None:
        receiver.execute(Log.GPGGA.output(args.interval))

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
                print(
                    f"{update.received_at.isoformat()} quality={fix.quality} "
                    f"lat={fix.latitude} lon={fix.longitude} "
                    f"height_msl={fix.altitude_msl} "
                    f"correction_age={fix.differential_age} "
                    f"connection={update.connection} reasons={assessment.reasons}",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
