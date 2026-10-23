"""Smooths pseudoranges with carrier phase from the command line."""

from collections.abc import Sequence

from examples._carrier_cli import carrier_main
from um982py.console import run


def main(argv: Sequence[str] | None = None) -> int:
    """Run a Hatch smoother on continuous GPS L1 and L5 arcs."""
    return carrier_main("hatch_smoothing", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
