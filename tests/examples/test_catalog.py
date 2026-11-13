"""Checks that every catalogued example imports and exposes a CLI."""

from __future__ import annotations

import ast
import importlib
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TEMP_REFERENCE = str(Path(os.sep) / "tmp") + os.sep

NAMES = tuple(
    sorted(
        path.name
        for path in EXAMPLES.iterdir()
        if path.is_dir() and not path.name.startswith((".", "_"))
    )
)
CSV_EXPERIMENTS = frozenset(
    {
        "spatial_tec",
        "noise_multipath",
        "multifrequency_slips",
        "uncertainty_coverage",
        "phase_fluctuations",
        "orbit_position_effect",
    }
)
WORKFLOW_EXAMPLES = frozenset(
    {
        "crs_transform",
        "field_recording",
        "live_position",
        "ntrip_sources",
        "postprocessed_rtk",
    }
)
SHARED_TESTS = {
    **dict.fromkeys(CSV_EXPERIMENTS, "test_scientific_cli.py"),
    **dict.fromkeys(WORKFLOW_EXAMPLES, "examples/test_workflow_examples.py"),
    "offline_ppp": "test_offline_ppp.py",
    "rinex_navigation": "test_rinex_nav.py",
}


def _fixture_replays() -> tuple[tuple[str, tuple[str, ...]], ...]:
    root = EXAMPLES.parent
    commands = []
    for readme in sorted(EXAMPLES.glob("*/README.md")):
        for block in re.findall(r"```bash\n(.*?)```", readme.read_text(), re.S):
            for line in block.replace("\\\n", " ").splitlines():
                try:
                    args = shlex.split(line, comments=True)
                except ValueError:
                    continue
                if (
                    len(args) < 5
                    or args[:2] != ["python", "-m"]
                    or not args[2].startswith("examples.")
                    or "--replay" not in args
                    or "--record" in args
                    or "--port" in args
                    or any(arg.startswith(("--record=", "--port=")) for arg in args)
                    or any(
                        ".." in Path(arg).parts
                        or "=/" in arg
                        or (arg.startswith("/") and not arg.startswith(TEMP_REFERENCE))
                        for arg in args
                    )
                    or any(token in line for token in ("|", ">", "$", ";", "&&"))
                ):
                    continue
                replay_index = args.index("--replay") + 1
                if replay_index >= len(args):
                    continue
                replay = args[replay_index]
                if replay.startswith("tests/fixtures/") and (root / replay).is_file():
                    commands.append((readme.parent.name, tuple(args)))
    return tuple(commands)


@pytest.mark.parametrize(("name", "args"), _fixture_replays())
def test_documented_fixture_replay(
    name: str, args: tuple[str, ...], tmp_path: Path
) -> None:
    """Run checked-in replay commands without touching the user's output paths."""
    root = EXAMPLES.parent
    command = [sys.executable, *args[1:]]
    for index in range(3, len(command)):
        argument = command[index]
        if argument.startswith("tests/fixtures/"):
            command[index] = str(root / argument)
        elif argument.startswith(TEMP_REFERENCE):
            command[index] = str(tmp_path / Path(argument).name)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, f"{name}: {result.stderr or result.stdout}"


@pytest.mark.parametrize("name", NAMES)
def test_example_directory_is_complete(name: str) -> None:
    directory = EXAMPLES / name
    assert (directory / "__init__.py").is_file()
    assert (directory / "__main__.py").is_file()
    assert (directory / "README.md").is_file()


@pytest.mark.parametrize("name", NAMES)
def test_example_module_imports(name: str) -> None:
    importlib.import_module(f"examples.{name}")


@pytest.mark.parametrize("name", NAMES)
def test_example_cli_responds_to_help(name: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", f"examples.{name}", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=EXAMPLES.parent,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    if name not in CSV_EXPERIMENTS | WORKFLOW_EXAMPLES | {"ice_motion", "offline_ppp"}:
        assert "--antenna" in result.stdout
    if name == "gnss_reflectometry":
        assert "--spectra-csv" in result.stdout
        assert "--dashboard" not in result.stdout


@pytest.mark.parametrize("name", NAMES)
def test_example_has_tests(name: str) -> None:
    relative = SHARED_TESTS.get(name, f"examples/test_{name}.py")
    assert (EXAMPLES.parent / "tests" / relative).is_file()


def test_example_index_lists_every_project() -> None:
    index = (EXAMPLES / "README.md").read_text()
    missing = [name for name in NAMES if f"`{name}`" not in index]
    assert not missing, f"examples/README.md does not link {missing}"


@pytest.mark.parametrize(
    ("name", "symbol"),
    [
        ("dop_geometry", "SatelliteGeometry"),
        ("ephemeris_orbit", "SatelliteState"),
        ("rtk_quality", "FixClass"),
    ],
)
def test_examples_do_not_reexport_library_apis(name: str, symbol: str) -> None:
    assert not hasattr(importlib.import_module(f"examples.{name}"), symbol)


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("examples.wls_position.__main__", "_gps_l1"),
        ("examples.wls_position.__main__", "select_position"),
        ("examples.wls_position.__main__", "select_gps_ephemerides"),
        ("examples.research_session.compare_reference", "_read_ecef_positions"),
        ("examples.ntrip_server.source", "_relay_body"),
    ],
)
def test_removed_example_helpers_are_not_reexported(module: str, name: str) -> None:
    assert not hasattr(importlib.import_module(module), name)


def test_examples_import_public_names() -> None:
    for path in EXAMPLES.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith(("um982py.", "examples."))
            ):
                private = [
                    name.name for name in node.names if name.name.startswith("_")
                ]
                assert not private, f"{path}:{node.lineno}: private imports {private}"


@pytest.mark.parametrize("name", ("", *NAMES))
def test_example_readme_links_resolve(name: str) -> None:
    readme = EXAMPLES / name / "README.md"
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme.read_text())
    for link in links:
        target = link.split("#", 1)[0]
        if target and ":" not in target:
            assert (readme.parent / target).exists(), f"{readme}: {link}"


@pytest.mark.parametrize("name", NAMES)
def test_example_readme_documents_a_source(name: str) -> None:
    text = (EXAMPLES / name / "README.md").read_text()
    assert "```bash" in text
    assert "python -m examples." in text
    assert any(
        marker in text for marker in ("(" + "19", "(20", "Reference", "et al", "Manual")
    ) or re.search(r"\[[^\]]+\]\(https?://[^)]+\)", text), (
        f"{name}/README.md cites no source"
    )
