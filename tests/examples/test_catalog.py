"""Checks that every catalogued example imports and exposes a CLI."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

NAMES = (
    "position_tracking",
    "coordinate_frames",
    "dop_geometry",
    "elevation_optimizer",
    "heading_attitude",
    "base_station_survey",
    "ntrip_server",
    "ntrip_client",
    "satellite_monitor",
    "signal_quality_report",
    "compressed_observation_audit",
    "interference_monitor",
    "rtk_quality",
    "ionosphere_tec",
    "scintillation_monitor",
    "gnss_reflectometry",
    "multipath_analysis",
    "cycle_slip_detection",
    "clock_stability",
    "time_transfer",
    "raw_data_tracking",
    "telemetry_bridge",
    "rinex_export",
    "ephemeris_orbit",
    "azel_crosscheck",
    "wls_position",
    "raim_fde",
    "klobuchar_vs_tec",
    "uere_budget",
    "pwv_meteorology",
    "cw_jamming",
    "antenna_gain_pattern",
    "multipath_vs_mask",
    "signal_group_study",
    "ttff_profile",
    "baseband_conformance",
    "baseband_notice_console",
    "spoof_dual_antenna",
    "attitude_budget",
    "navigation_messages",
    "navigation_message_hex",
    "doppler_velocity",
    "vadase",
    "hatch_smoothing",
    "code_carrier_divergence",
    "zero_baseline_lab",
    "sidereal_multipath",
    "broadcast_orbit_audit",
    "b2b_correction_audit",
    "rtk_outage_lab",
    "clock_jump_forensics",
    "tracking_field_lab",
    "dual_antenna_rf_audit",
    "precise_fix",
    "triple_frequency_closure",
    "baseband_epoch_audit",
    "ppp_filter_inspector",
    "has_b2b_ppp_fix",
    "research_session",
    "qzss_disaster_report",
    "satellite_health_timeline",
    "unattended_station",
    "polar_ionosphere",
    "ice_motion",
    "journey_track",
)


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
    if name != "ice_motion":
        assert "--antenna" in result.stdout
    if name == "gnss_reflectometry":
        assert "--spectra-csv" in result.stdout
        assert "--dashboard" not in result.stdout


@pytest.mark.parametrize("name", NAMES)
def test_example_has_tests(name: str) -> None:
    assert (EXAMPLES.parent / "tests" / "examples" / f"test_{name}.py").is_file()


def test_example_index_lists_every_project() -> None:
    index = (EXAMPLES / "README.md").read_text()
    missing = [name for name in NAMES if f"`{name}`" not in index]
    assert not missing, f"examples/README.md does not link {missing}"


@pytest.mark.parametrize("name", NAMES)
def test_example_readme_documents_a_source(name: str) -> None:
    text = (EXAMPLES / name / "README.md").read_text()
    assert "```bash" in text
    assert "python -m examples." in text
    assert any(
        marker in text for marker in ("(" + "19", "(20", "Reference", "et al", "Manual")
    ), f"{name}/README.md cites no source"
