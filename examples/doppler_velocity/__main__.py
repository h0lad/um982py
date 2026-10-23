"""Solves broadcast-corrected Doppler velocity from the command line."""

from collections.abc import Sequence

from examples._gps_motion import motion_main
from um982py.console import run


def main(argv: Sequence[str] | None = None) -> int:
    """Estimate GPS L1 velocity and receiver clock drift."""
    return motion_main("doppler_velocity", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
