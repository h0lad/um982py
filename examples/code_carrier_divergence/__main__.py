"""Track code-carrier divergence across continuous arcs."""

from collections.abc import Sequence

from examples._carrier_cli import carrier_main
from examples._console import run


def main(argv: Sequence[str] | None = None) -> int:
    """Report divergence with a user-selected experimental threshold."""
    return carrier_main("code_carrier_divergence", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
