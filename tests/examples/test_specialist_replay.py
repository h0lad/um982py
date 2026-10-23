"""Runs specialist command lines against RTKLIB and labelled wire captures."""

from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from tests.examples._specialist import FIXTURES

CASES = (
    (
        "doppler_velocity",
        "rtklib-motion.bin",
        ["--truth-velocity", "0.03", "-0.02", "0.01"],
    ),
    ("vadase", "rtklib-motion.bin", ["--truth-velocity", "0.03", "-0.02", "0.01"]),
    ("hatch_smoothing", "rtklib-motion.bin", []),
    ("code_carrier_divergence", "rtklib-motion.bin", []),
    (
        "zero_baseline_lab",
        "rtklib-motion.bin",
        ["--reference", str(FIXTURES / "rtklib-motion.bin"), "--reference-prn", "1"],
    ),
    ("clock_jump_forensics", "rtklib-motion.bin", []),
    (
        "sidereal_multipath",
        "repeat-validation.bin",
        ["--training", str(FIXTURES / "repeat-training.bin")],
    ),
    (
        "tracking_field_lab",
        "labelled-tracking.bin",
        ["--labels", str(FIXTURES / "tracking-labels.csv")],
    ),
    (
        "broadcast_orbit_audit",
        "rtklib-motion.bin",
        ["--sp3", str(FIXTURES / "rtklib-motion.sp3")],
    ),
    (
        "rtk_outage_lab",
        "labelled-outage.bin",
        [
            "--outages",
            str(FIXTURES / "outages.csv"),
            "--truth-ecef",
            "3782565.552836",
            "899482.807107",
            "5039202.934866",
        ],
    ),
    (
        "b2b_correction_audit",
        "labelled-b2b.bin",
        ["--navigation", str(FIXTURES / "navigation-issues.csv")],
    ),
)


@pytest.mark.parametrize("name,capture,extra", CASES, ids=[case[0] for case in CASES])
def test_cli_matches_independently_labelled_experiment(
    name: str,
    capture: str,
    extra: list[str],
    tmp_path: Path,
) -> None:
    module = importlib.import_module(f"examples.{name}.__main__")
    output = tmp_path / "result.json"
    assert (
        module.main(
            ["--replay", str(FIXTURES / capture), "--json", str(output), *extra]
        )
        == 0
    )
    data: dict[str, Any] = json.loads(output.read_text())
    if name in ("vadase", "doppler_velocity"):
        assert data["velocity_rmse_mps"] < 2e-4
        assert len(data["epochs"]) == (15 if name == "vadase" else 16)
        assert not data["rejected"]
    elif name == "hatch_smoothing":
        for series in data["signals"]:
            assert len(series["samples"]) == 16
            for row in series["samples"]:
                assert row["smoothed_m"] == pytest.approx(row["raw_m"], abs=1e-6)
    elif name == "code_carrier_divergence":
        for series in data["signals"]:
            assert max(abs(row["change_m"]) for row in series["samples"]) < 1e-7
    elif name == "zero_baseline_lab":
        assert len(data["estimates"]) == 5
        assert all(row["phase_dd_std_m"] == 0 for row in data["estimates"])
    elif name == "clock_jump_forensics":
        assert data["tested_intervals"] == 15
        assert data["events"] == []
    elif name == "sidereal_multipath":
        assert data["coverage"] == 1
        assert data["corrected_rms_m"] == pytest.approx(
            12 / 143 * math.sqrt(32 / 3), abs=1e-10
        )
    elif name == "tracking_field_lab":
        hypothesis = next(row for row in data["hypotheses"] if row["offset"] == 20)
        assert hypothesis["correlation"] == pytest.approx(1)
        assert hypothesis["pairs"] == 8
    elif name == "broadcast_orbit_audit":
        assert len(data["differences"]) == 96
        assert data["position_3d_rms_m"] < 0.001
    elif name == "rtk_outage_lab":
        assert data["outages"][0]["recovery_after_end_s"] == 2
        assert data["outages"][0]["maximum_truth_error_m"] == pytest.approx(5)
    elif name == "b2b_correction_audit":
        assert len(data["checks"]) == 3
        assert [row["age_seconds"] for row in data["checks"]] == [1, 1, 1]
        assert all(not row["flags"] for row in data["checks"])


def test_type_two_reserved_byte_is_not_a_prn_mask_issue() -> None:
    from um982py.capture import load_records
    from um982py.commands import Log

    record = load_records(FIXTURES / "labelled-b2b.bin", Log.PPPB2BINFO2)[0]
    assert record.integer("reserved") == 9
    assert "iodp" not in record


def test_replay_retains_wire_order_across_correction_log_types(tmp_path: Path) -> None:
    from um982py.capture import capture_records, read_frames
    from um982py.commands import Log
    from um982py.console import experiment_parser
    from um982py.messages import Record

    frames = read_frames(FIXTURES / "labelled-b2b.bin")
    path = tmp_path / "reordered.bin"
    path.write_bytes(frames[1].raw + frames[0].raw + frames[2].raw)
    parser = experiment_parser("test", "test")
    args = parser.parse_args(["--replay", str(path)])
    ordered: list[Record] = []
    capture_records(
        args, [Log.PPPB2BINFO1, Log.PPPB2BINFO2, Log.PPPB2BINFO7], arrival_order=ordered
    )
    assert [record.name for record in ordered] == [
        "PPPB2BINFO2",
        "PPPB2BINFO1",
        "PPPB2BINFO7",
    ]


@pytest.mark.parametrize(
    "option",
    ["max-gap", "tau", "sigma", "phase-tolerance", "cell-degrees", "mask-max-age"],
)
def test_invalid_experiment_controls_are_rejected_before_capture(option: str) -> None:
    from um982py.console import experiment_parser

    parser = experiment_parser("test", "test")
    parser.add_argument("--" + option, type=float)
    with pytest.raises(SystemExit) as failure:
        parser.parse_args(["--" + option, "-1"])
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "option,source",
    [
        ("--sp3", "rtklib-motion.sp3"),
        ("--training", "repeat-training.bin"),
        ("--reference", "rtklib-motion.bin"),
        ("--labels", "tracking-labels.csv"),
    ],
)
def test_reference_inputs_cannot_be_overwritten_by_json_output(
    option: str, source: str
) -> None:
    from um982py.console import experiment_parser

    parser = experiment_parser("test", "test")
    parser.add_argument(option, type=Path)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(
            [
                "--replay",
                str(FIXTURES / "rtklib-motion.bin"),
                option,
                str(FIXTURES / source),
                "--json",
                str(FIXTURES / source),
            ]
        )
    assert error.value.code == 2
