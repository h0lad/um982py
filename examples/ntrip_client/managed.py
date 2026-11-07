"""Relay NTRIP corrections with the library's recoverable session API."""

import argparse
import math
import os
import sys
from collections.abc import Sequence
from threading import Event, Timer

from examples.ntrip_client import gga_from_fix
from um982py import NtripClient, Receiver, ReceiverStream, RtkSession
from um982py.commands import queries
from um982py.errors import ResponseTimeout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", required=True, help="serial device or tcp://host:port"
    )
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--caster", required=True, help="http(s) caster mountpoint URL")
    parser.add_argument("--username")
    parser.add_argument("--password-env", default="NTRIP_PASSWORD")
    parser.add_argument("--ntrip-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--no-gga", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("duration must be finite and positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    password = os.getenv(args.password_env) if args.username is not None else None
    if args.username is not None and password is None:
        parser.error(f"set {args.password_env} to the caster password")

    with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
        stream = ReceiverStream(receiver)
        stream.start()

        def gga() -> bytes | None:
            try:
                fix = stream.execute(queries.fix(), timeout=args.timeout).result()
            except ResponseTimeout:
                return None
            return gga_from_fix(fix) if fix.valid else None

        def client() -> NtripClient:
            return NtripClient(
                args.caster,
                username=args.username,
                password=password,
                initial_gga=None if args.no_gga else gga(),
                timeout=args.timeout,
                version=args.ntrip_version,
            )

        session = RtkSession(stream, client, gga_provider=None if args.no_gga else gga)
        stop = Event()
        timer = Timer(args.duration, stop.set)
        timer.start()
        try:
            session.run(stop)
        finally:
            timer.cancel()
            stream.close()
        health = session.health()
        print(
            f"RTCM frames: {health.frames_forwarded}; reconnects: {health.reconnects}; "
            f"state: {health.state}",
            file=sys.stderr,
        )
        return 0 if health.frames_forwarded else 1


if __name__ == "__main__":
    raise SystemExit(main())
