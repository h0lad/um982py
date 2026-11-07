"""List advertised NTRIP mountpoints and their distance from a position."""

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict

from um982py import fetch_sourcetable
from um982py.geodesy import haversine_distance


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("caster", help="caster root URL, for example https://host:443")
    parser.add_argument("--username")
    parser.add_argument("--password-env", default="NTRIP_PASSWORD")
    parser.add_argument("--version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--position", type=float, nargs=2, metavar=("LAT", "LON"))
    args = parser.parse_args(argv)
    password = os.environ.get(args.password_env) if args.username else None
    if args.username and password is None:
        raise ValueError(f"Set {args.password_env} for the NTRIP password")
    sources = fetch_sourcetable(
        args.caster, username=args.username, password=password, version=args.version
    )
    if args.position is not None:
        latitude, longitude = args.position
        haversine_distance(latitude, longitude, latitude, longitude)
        rows = [(source, source.distance_to(latitude, longitude)) for source in sources]
        rows.sort(key=lambda row: float("inf") if row[1] is None else row[1])
    else:
        rows = [(source, None) for source in sources]
    print(
        json.dumps(
            [{**asdict(source), "distance_m": distance} for source, distance in rows],
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
