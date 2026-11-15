"""Regression cases where a runnable example previously implied wrong evidence."""

import argparse
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from examples._console import ExampleParser
from examples._console_capture import selected_log
from examples.cycle_slip_detection import (
    Observation,
    detect_slips,
    doppler_residuals,
    geometry_free_slips,
)
from examples.wls_position import RangeMeasurement, solve_position

from examples import _scientific_cli
from um982py.antenna import AntennaLog, antenna_log, swap_antenna
from um982py.commands import Log
from um982py.messages.enums import SatelliteSystem

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
@pytest.mark.parametrize("output", ["json", "timeline_csv", "secondary_output"])
def test_report_paths_cannot_destroy_input(
    tmp_path: Path, alias: str, output: str
) -> None:
    source = tmp_path / "input.bin"
    original = b"irreplaceable field observations"
    source.write_bytes(original)
    destination = tmp_path / "report.json"
    if alias == "same":
        destination = source
    elif alias == "symlink":
        destination.symlink_to(source)
    else:
        destination.hardlink_to(source)
    parser = ExampleParser()
    parser.add_argument("--navigation", type=Path, nargs="+")
    parser.add_argument(f"--{output.replace('_', '-')}", type=Path)
    with pytest.raises(SystemExit) as raised:
        parser.parse_args(
            [
                "--navigation",
                str(source),
                f"--{output.replace('_', '-')}",
                str(destination),
            ]
        )
    assert raised.value.code == 2
    assert source.read_bytes() == original


def test_reports_cannot_overwrite_each_other(tmp_path: Path) -> None:
    parser = ExampleParser()
    parser.add_argument("--checks-csv", type=Path)
    parser.add_argument("--json", type=Path)
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--checks-csv", str(tmp_path / "out"), "--json", str(tmp_path / "out")]
        )


def test_csv_experiment_cannot_replace_its_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "phase.csv"
    original = "arc,time_s,phase_m\na,0,1\na,1,2\na,2,3\n"
    source.write_text(original)
    monkeypatch.setattr(
        "sys.argv",
        ["phase_fluctuations", "--input", str(source), "--json", str(source)],
    )
    with pytest.raises(SystemExit) as raised:
        _scientific_cli.main("phase_fluctuations")
    assert raised.value.code == 2
    assert source.read_text() == original


@pytest.mark.parametrize("log", [Log.BESTPOS, Log.BESTXYZ, Log.BESTNAV, Log.BESTVEL])
def test_navigation_swaps_use_logical_identity(log: Log) -> None:
    secondary = antenna_log(log, 2)
    assert isinstance(secondary, AntennaLog)
    assert swap_antenna(log).wire == secondary.wire
    assert swap_antenna(secondary).wire == log
    for antenna, swapped, expected in [
        ("primary", False, log),
        ("primary", True, secondary.wire),
        ("secondary", False, secondary.wire),
        ("secondary", True, log),
    ]:
        result = selected_log(
            argparse.Namespace(antenna=antenna, swap_antennas=swapped), log
        )
        assert (result.wire if isinstance(result, AntennaLog) else result) == expected


def test_primary_only_log_checks_effective_antenna() -> None:
    assert antenna_log(Log.PPPDOP, 2, swapped=True) is Log.PPPDOP
    with pytest.raises(ValueError, match="no verified secondary"):
        antenna_log(Log.PPPDOP, 1, swapped=True)


@pytest.mark.parametrize("name", ["wls_position", "raim_fde", "klobuchar_vs_tec"])
def test_secondary_replay_cannot_fall_back_to_primary_measurements(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = importlib.import_module(f"examples.{name}.__main__")
    arguments = [
        "--replay",
        str(FIXTURES / "captures-live" / "RANGEA.bin"),
        "--position",
        str(FIXTURES / "captures-live" / "BESTPOSA.bin"),
        "--antenna",
        "secondary",
    ]
    if name == "klobuchar_vs_tec":
        arguments.extend(
            [
                "--ionosphere",
                str(FIXTURES / "captures-live" / "GPSIONA.bin"),
                "--satvis",
                str(FIXTURES / "captures-live" / "SATVIS2A.bin"),
            ]
        )
    else:
        arguments.extend(
            ["--ephemeris", str(FIXTURES / "captures-live" / "GPSEPHA.bin")]
        )
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 2
    message = capsys.readouterr().err
    assert (
        "frames are required" in message
        if name == "klobuchar_vs_tec"
        else "a RANGE frame" in message
    )


def test_slip_detector_splits_gaps_and_lock_resets_without_discarding_slips() -> None:
    samples = [
        Observation(7, 0, 0, 1, 100),
        Observation(7, 1, 1, 1, 101),
        Observation(7, 10, 110, 1, 110),  # Unobserved interval; arbitrary ambiguity.
        Observation(7, 11, 113, 1, 111),  # Two-cycle jump within an observed arc.
        Observation(7, 12, 200, 1, 0),  # Explicit lock reset.
        Observation(7, 13, 201, 1, 1),
    ]
    assert doppler_residuals(samples) == ((1, 0), (11, 2), (13, 0))
    slips = detect_slips(samples)
    assert [(slip.epoch, slip.cycles) for slip in slips] == [(11, 2)]


@pytest.mark.parametrize("epochs", [(1, 1), (2, 1)])
def test_slip_detector_rejects_duplicate_or_reversed_epochs(
    epochs: tuple[int, int],
) -> None:
    with pytest.raises(ValueError, match="increase strictly"):
        detect_slips([Observation(7, time, 0, 0) for time in epochs])


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), 0, -1])
def test_slip_threshold_must_be_finite_and_positive(threshold: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        detect_slips([], threshold_cycles=threshold)
    with pytest.raises(ValueError, match="finite and positive"):
        geometry_free_slips([], threshold_metres=threshold)


def test_geometry_free_does_not_bridge_missing_epochs() -> None:
    from examples.cycle_slip_detection import DualFrequencyPhase

    first = DualFrequencyPhase(7, 0, 1575.42e6, 100, 1227.60e6, 100)
    jumped = replace(first, epoch=10, high_cycles=110)
    assert geometry_free_slips([first, jumped]) == ()
    assert geometry_free_slips([first, replace(jumped, epoch=1)])


def test_single_epoch_is_insufficient_for_a_slip_test(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from examples.cycle_slip_detection.__main__ import main

    assert main(["--replay", str(FIXTURES / "captures" / "RANGEB.bin")]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "insufficient_data"
    assert report["tested_increments"] == 0


@pytest.mark.parametrize("mixed", [False, True])
def test_wls_rejects_false_redundancy_and_unmodelled_inter_system_bias(
    mixed: bool,
) -> None:
    observations = [
        RangeMeasurement(SatelliteSystem.GPS, i, 20e6, 0, 0, 20e6, 1)
        for i in range(1, 5)
    ]
    observations[-1] = (
        replace(observations[-1], system=SatelliteSystem.GALILEO)
        if mixed
        else observations[0]
    )
    with pytest.raises(
        ValueError, match=r"one constellation|one independent measurement"
    ):
        solve_position(observations, (0, 0, 0, 0))


@pytest.mark.parametrize(
    "name",
    [
        "ephemeris_orbit",
        "multipath_vs_mask",
        "spoof_dual_antenna",
        "baseband_conformance",
    ],
)
def test_unrelated_wire_frames_do_not_complete_an_analysis(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = importlib.import_module(f"examples.{name}.__main__")
    assert cli.main(["--replay", str(FIXTURES / "versiona.bin")]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] in ("insufficient_data", "incomplete_checks")


def test_hex_default_stdout_is_one_json_document(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from examples.navigation_message_hex.__main__ import main

    assert main(["--replay", str(FIXTURES / "captures-live" / "GPSEPHB.bin")]) == 0
    streams = capsys.readouterr()
    assert json.loads(streams.out)["messages"]
    assert "GPS GPSEPH" in streams.err


def test_hex_swap_routes_explicit_secondary_log_back_to_primary() -> None:
    from examples.navigation_message_hex.__main__ import _targets

    assert [log for _, log in _targets(["GPS"], ["RANGEH"], swapped=True)] == [
        Log.GPSEPH,
        Log.RANGE,
    ]


def test_coordinate_example_rejects_unrelated_position_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examples.coordinate_frames import __main__ as cli

    from test_position_selection import position
    from um982py.messages import Record

    near = position(2441, 100)
    baseline = Record(
        "BSLNENUHD",
        (
            ("p_sol_status", "SOL_COMPUTED"),
            ("delta_1", 1.0),
            ("delta_2", 0.0),
            ("delta_3", 0.0),
        ),
        near.message,
    )
    monkeypatch.setattr(
        cli,
        "capture_records",
        lambda *args, **kwargs: {
            "BESTXYZ": (position(2441, 110),),
            "BSLNENUHD": (baseline,),
        },
    )
    with pytest.raises(ValueError, match="epoch tolerance"):
        cli.main(["--replay", "unused.bin"])


def test_coordinate_swap_keeps_the_physical_primary_origin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.coordinate_frames import __main__ as cli

    from test_position_selection import position
    from um982py.geodesy import receiver_ecef
    from um982py.messages import Record

    primary = position(2441, 100)
    secondary = replace(
        primary,
        name="BESTNAVXYZH",
        entries=tuple(
            (key, float(value) + 100 if key == "p_x" else value)
            for key, value in primary.entries
        ),
    )
    baseline = Record(
        "BSLNENUHD",
        (
            ("p_sol_status", "SOL_COMPUTED"),
            ("delta_1", 1.0),
            ("delta_2", 0.0),
            ("delta_3", 0.0),
        ),
        primary.message,
    )

    def captured(
        args: argparse.Namespace, logs: list[Log | AntennaLog], **kwargs: object
    ) -> dict[str, tuple[Record, ...]]:
        selected = {log.value: selected_log(args, log) for log in logs}
        assert selected["BESTXYZ"].wire_name(binary=True) == "BESTNAVXYZHB"
        assert selected["BESTNAVXYZ"].wire_name(binary=True) == "BESTNAVXYZB"
        return {
            "BESTXYZ": (secondary,),
            "BESTNAVXYZ": (primary,),
            "BSLNENUHD": (baseline,),
        }

    monkeypatch.setattr(cli, "capture_records", captured)
    assert cli.main(["--replay", "unused.bin", "--swap-antennas"]) == 0
    report = json.loads(capsys.readouterr().out)
    from um982py.geodesy import ecef_from_geodetic

    origin = report["origin"]
    assert ecef_from_geodetic(
        origin["latitude"], origin["longitude"], origin["height"]
    ) == pytest.approx(receiver_ecef(primary))
    assert report["selected_antenna"] == 2
    assert "not an independent" in report["validation"]


def test_spoof_heading_requires_matching_computed_baseline_epochs() -> None:
    from examples.spoof_dual_antenna.__main__ import Capture, _heading_agreement

    from test_position_selection import position
    from um982py.capture import load_records

    origin = position(2441, 100)
    enu = replace(
        load_records(FIXTURES / "captures" / "BSLNENUHDA.bin", Log.BSLNENUHD)[0],
        message=origin.message,
    )
    ecef = replace(
        load_records(FIXTURES / "captures" / "BSLNXYZHDA.bin", Log.BSLNXYZHD)[0],
        message=origin.message,
    )
    capture = Capture(enu=(enu,), ecef=(ecef,), position=(origin,))
    assert _heading_agreement(capture) is not None
    stale_ecef = replace(ecef, message=position(2441, 110).message)
    assert _heading_agreement(replace(capture, ecef=(stale_ecef,))) is None
    assert _heading_agreement(replace(capture, position=(position(2441, 110),))) is None
    uncomputed = replace(
        enu,
        entries=tuple(
            (key, "INSUFFICIENT_OBS" if key == "p_sol_status" else value)
            for key, value in enu.entries
        ),
    )
    assert _heading_agreement(replace(capture, enu=(uncomputed,))) is None
