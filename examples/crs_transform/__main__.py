"""Transform a 3D coordinate and print the selected PROJ operation."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from um982py import transform_coordinate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="source 3D CRS, such as EPSG:4979")
    parser.add_argument("target", help="target 3D CRS, such as EPSG:4978")
    parser.add_argument("coordinate", type=float, nargs=3, metavar=("X", "Y", "Z"))
    parser.add_argument("--epoch", type=float, help="coordinate epoch in decimal years")
    parser.add_argument("--promote-to-3d", action="store_true")
    args = parser.parse_args(argv)
    result = transform_coordinate(
        tuple(args.coordinate),
        args.source,
        args.target,
        coordinate_epoch=args.epoch,
        promote_to_3d=args.promote_to_3d,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
