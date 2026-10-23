"""Solves continuous-arc variometric displacement from the command line."""

from collections.abc import Sequence

from examples._gps_motion import motion_main
from um982py.console import run


def main(argv: Sequence[str] | None = None) -> int:
    """Estimate interval displacement without integrating across missing arcs."""
    return motion_main("vadase", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
