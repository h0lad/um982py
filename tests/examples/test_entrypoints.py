"""Ensure each example entry point can be discovered without hardware."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted(
    path.parent.name for path in (ROOT / "examples").glob("*/__main__.py")
)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_help(name: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", f"examples.{name}", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
