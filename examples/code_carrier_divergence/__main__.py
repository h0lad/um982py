"""Reports code-minus-carrier divergence from the command line."""

from collections.abc import Sequence

from examples._carrier_cli import carrier_main
from um982py.console import run


def main(argv: Sequence[str] | None = None) -> int:
    """Report divergence with a user-selected experimental threshold."""
    return carrier_main("code_carrier_divergence", argv)


if __name__ == "__main__":
    raise SystemExit(run(main))
