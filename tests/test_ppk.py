import json
import os
import sys
from pathlib import Path

import pytest

from um982py.ppk import PostProcessingError, run_ppk


def rinex(path: Path, kind: str) -> Path:
    path.write_text(
        f"{'3.05':>9}{'':11}{kind:<20}{'':20}RINEX VERSION / TYPE\n"
        f"{'':60}END OF HEADER\n",
        encoding="ascii",
    )
    return path


def solver(path: Path, solution: str) -> Path:
    script = (
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text({solution!r})\n"
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        rinex(tmp_path / "rover.obs", "OBSERVATION DATA"),
        rinex(tmp_path / "base.obs", "OBSERVATION DATA"),
        rinex(tmp_path / "nav.nav", "NAVIGATION DATA"),
    )


def test_ppk_records_inputs_solver_and_results(tmp_path: Path) -> None:
    rover, base, nav = inputs(tmp_path)
    executable = solver(
        tmp_path / "solver",
        "% test\n2020/01/01 00:00:00.000 50.0 8.0 100.0 1 12\n",
    )
    result = run_ppk(
        str(rover),
        str(base),
        [str(nav)],
        str(tmp_path / "result"),
        executable=str(executable),
        base_ecef=(6378137, 0, 0),
        reference_frame="test frame",
        reference_epoch=2020,
    )
    manifest = json.loads(result.manifest.read_text())
    assert result.epochs == 1 and result.quality_counts == ((1, 1),)
    assert (
        manifest["status"] == "complete" and manifest["reference_frame"] == "test frame"
    )
    assert len(manifest["input_sha256"]) == 3
    assert manifest["command"][0] == str(executable)
    assert len(manifest["solution_sha256"]) == 64
    with pytest.raises(FileExistsError):
        run_ppk(
            rover,
            base,
            (nav,),
            tmp_path / "result",
            executable=str(executable),
            base_ecef=(6378137, 0, 0),
            reference_frame="test frame",
        )


def test_ppk_no_solution_is_failure_with_manifest(tmp_path: Path) -> None:
    rover, base, nav = inputs(tmp_path)
    executable = solver(tmp_path / "solver", "% no position\n")
    with pytest.raises(PostProcessingError, match="no position solutions"):
        run_ppk(
            rover,
            base,
            (nav,),
            tmp_path / "result",
            executable=str(executable),
            base_ecef=(6378137, 0, 0),
            reference_frame="test frame",
        )
    manifest = json.loads((tmp_path / "result/run.json").read_text())
    assert manifest["status"] == "failed"


def test_ppk_rejects_wrong_rinex_type_before_creating_output(tmp_path: Path) -> None:
    rover, base, nav = inputs(tmp_path)
    with pytest.raises(ValueError, match="RINEX header"):
        run_ppk(
            nav,
            base,
            (rover,),
            tmp_path / "result",
            base_ecef=(6378137, 0, 0),
            reference_frame="test frame",
        )
    assert not (tmp_path / "result").exists()


def test_ppk_with_rtklib_sample(tmp_path: Path) -> None:
    repo = os.environ.get("RTKLIB_REPOSITORY")
    executable = os.environ.get("RTKLIB_RNX2RTKP")
    if not repo or not executable:
        pytest.skip("set RTKLIB_REPOSITORY and RTKLIB_RNX2RTKP")
    root = Path(repo) / "test/data/rinex"
    result = run_ppk(
        root / "07590920.05o",
        root / "30400920.05o",
        (root / "07590920.05n",),
        tmp_path / "result",
        executable=executable,
        base_ecef=(-3978242.4348, 3382841.1715, 3649902.7667),
        reference_frame="RTKLIB sample approximate frame",
        mode="static",
    )
    assert result.epochs > 0 and result.solution.is_file()
