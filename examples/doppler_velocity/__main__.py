"""Solve receiver velocity and clock drift from Doppler."""

from collections.abc import Sequence

from examples._console import run
from examples._gps_motion import motion_main


def main(argv: Sequence[str] | None = None) -> int:
    """Estimate GPS L1 velocity and receiver clock drift."""
    return motion_main("doppler_velocity", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
