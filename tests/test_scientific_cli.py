"""Exercise every documented experiment with its shipped sample."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

NAMES = (
    "spatial_tec",
    "noise_multipath",
    "multifrequency_slips",
    "uncertainty_coverage",
    "phase_fluctuations",
    "orbit_position_effect",
)


@pytest.mark.parametrize("name", NAMES)
def test_documented_sample(name: str, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "result.json"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            f"examples.{name}",
            "--input",
            f"examples/{name}/sample.csv",
            "--json",
            str(output),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text())
    assert result["experiment"] == name
    assert result["result"]


def test_invalid_input_reports_failure(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    bad = tmp_path / "bad.csv"
    bad.write_text("time_s,phase_m,arc\n0,1,a\n2,2,a\n1,3,a\n")
    proc = subprocess.run(
        [sys.executable, "-m", "examples.phase_fluctuations", "--input", str(bad)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "times must increase" in proc.stderr
    assert proc.stdout == ""
