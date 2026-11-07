"""Process rover and base RINEX files with RTKLIB rnx2rtkp."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from um982py import run_ppk


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rover", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("navigation", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-ecef", type=float, nargs=3, required=True, metavar=("X", "Y", "Z")
    )
    parser.add_argument("--reference-frame", required=True)
    parser.add_argument("--reference-epoch", type=float)
    parser.add_argument("--mode", choices=("kinematic", "static"), default="kinematic")
    parser.add_argument("--frequencies", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--elevation-mask", type=float, default=15)
    parser.add_argument("--executable", default="rnx2rtkp")
    args = parser.parse_args(argv)
    result = run_ppk(
        args.rover,
        args.base,
        tuple(args.navigation),
        args.output,
        base_ecef=tuple(args.base_ecef),
        reference_frame=args.reference_frame,
        reference_epoch=args.reference_epoch,
        mode=args.mode,
        frequencies=args.frequencies,
        elevation_mask=args.elevation_mask,
        executable=args.executable,
    )
    print(f"{result.epochs} solutions written to {result.solution}")
    print(f"RTKLIB quality counts: {dict(result.quality_counts)}")
    print(f"Run manifest: {result.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
