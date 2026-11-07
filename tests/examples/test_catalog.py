"""Checks that every catalogued example imports and exposes a CLI."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

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


@pytest.mark.parametrize("name", NAMES)
def test_example_directory_is_complete(name: str) -> None:
    directory = EXAMPLES / name
    assert (directory / "__init__.py").is_file()
    assert (directory / "__main__.py").is_file()
    assert (directory / "README.md").is_file()


@pytest.mark.parametrize("name", NAMES)
def test_example_module_imports_and_documents_itself(name: str) -> None:
    module = importlib.import_module(f"examples.{name}")
    docstring = (module.__doc__ or "").strip()
    assert docstring, f"examples.{name} has no module docstring"
    assert len(docstring.splitlines()) == 1


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
