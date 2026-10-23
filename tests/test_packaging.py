"""Source releases must retain the runnable examples used by their tests."""

import subprocess
import sys
import tarfile
from pathlib import Path


def test_source_distribution_contains_examples(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "hatchling",
            "build",
            "-t",
            "sdist",
            "-d",
            str(tmp_path),
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    archive_path = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(archive_path) as archive:
        names = {name.partition("/")[2] for name in archive.getnames()}
    for path in project.joinpath("examples").rglob("*"):
        if path.suffix in (".py", ".md", ".txt"):
            assert path.relative_to(project).as_posix() in names
    assert "src/um982py/py.typed" in names
