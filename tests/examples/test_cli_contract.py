"""Checks that every example imports safely and fails without hanging."""

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from um982py import Receiver

PROJECT = Path(__file__).resolve().parents[2]
NAMES = sorted(
    path.parent.name for path in (PROJECT / "examples").glob("*/__main__.py")
)


@pytest.mark.parametrize("name", NAMES)
def test_entry_point_import_has_no_receiver_or_cli_side_effect(name: str) -> None:
    with patch.object(
        Receiver, "serial", side_effect=AssertionError("import opened a receiver")
    ):
        module = importlib.import_module(f"examples.{name}.__main__")
    assert callable(module.main)


@pytest.mark.parametrize("name", NAMES)
def test_missing_replay_file_fails_promptly_without_traceback(
    name: str, tmp_path: Path
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            f"examples.{name}",
            "--replay",
            str(tmp_path / "missing.bin"),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
