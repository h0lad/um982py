"""Exercises the dual-service PPP fix against synthetic and recorded fixes."""

from dataclasses import replace
from pathlib import Path

import pytest
from examples.has_b2b_ppp_fix import (
    PppEpoch,
    convergence,
    divergence_tally,
    mean_fix,
    position_label,
    ppp_epochs,
    precision_statistics,
    xyz_fallback,
)

from um982py.capture import decode_records, read_frames
from um982py.commands import Log
from um982py.messages import Record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def epoch(
    index: int,
    *,
    pos_type: int = 69,
    lat: float = 48.0,
    lon: float = 11.0,
    hgt: float = 500.0,
    h_sigma: float = 0.05,
    v_sigma: float = 0.08,
) -> PppEpoch:
    """One synthetic PPPNAV fix drifting slightly around a static point."""
    return PppEpoch(
        1000.0 + index,
        lat + 1e-9 * index,
        lon + 1e-9 * index,
        hgt + 0.001 * index,
        pos_type,
        0,
        h_sigma,
        h_sigma,
        v_sigma,
        22,
        20,
        2.0,
    )


def test_position_label_names_native_types() -> None:
    assert position_label(69) == "PPP"
    assert position_label(68) == "PPP_CONVERGING"
    assert position_label(999) == "999"


def test_fixed_ppp_types_are_included_in_convergence() -> None:
    items = [epoch(0, pos_type=70), epoch(1, pos_type=71)]
    result = convergence(items, target_horizontal=0.10, target_vertical=0.20)
    assert (result.ppp, result.converged_fix) == (2, 2)
    assert result.converged


def test_uncomputed_ppp_is_not_averaged_or_reported_as_converged() -> None:
    invalid = replace(epoch(1, pos_type=70), solution_status=1, latitude=70.0)
    result = convergence(
        [epoch(0), invalid], target_horizontal=0.10, target_vertical=0.20
    )
    assert not result.converged
    assert result.ppp == 1
    fix = mean_fix([epoch(0), invalid])
    assert fix.epochs == 1
    assert fix.latitude == pytest.approx(48.0)


def test_convergence_reports_sigma_improvement() -> None:
    items = [
        epoch(0, pos_type=68, h_sigma=1.2, v_sigma=2.0),
        epoch(1, pos_type=68, h_sigma=0.4, v_sigma=0.6),
        epoch(2, pos_type=69, h_sigma=0.05, v_sigma=0.08),
    ]
    model = convergence(items, target_horizontal=0.10, target_vertical=0.20)
    assert (model.total, model.ppp, model.converged_fix) == (3, 3, 1)
    assert model.improvement == pytest.approx(24.0)
    assert model.converged
    assert dict(model.classes)["PPP"] == 1


def test_convergence_rejects_nonfinite_targets() -> None:
    with pytest.raises(ValueError, match="finite"):
        convergence([epoch(0)], target_horizontal=float("nan"), target_vertical=0.2)
    with pytest.raises(ValueError, match="positive"):
        convergence([epoch(0)], target_horizontal=0.0, target_vertical=0.2)


def test_mean_fix_averages_static_ppp_epochs() -> None:
    fix = mean_fix([epoch(index) for index in range(10)])
    assert fix.latitude == pytest.approx(48.0, abs=1e-7)
    assert fix.longitude == pytest.approx(11.0, abs=1e-7)
    assert fix.source == "PPPNAV"
    assert fix.epochs == 10
    assert fix.horizontal_scatter < 0.05


def test_mean_fix_needs_ppp_when_requested() -> None:
    with pytest.raises(ValueError, match="no PPP"):
        mean_fix([epoch(0, pos_type=16)], ppp_only=True)
    fallback = mean_fix([epoch(0, pos_type=16)], ppp_only=False)
    assert fallback.epochs == 1


def test_divergence_tally_reports_worst_signal() -> None:
    tally = divergence_tally(
        [("sys0-prn01-sig00", 10, 1, 0, 0.004), ("sys4-prn19-sig01", 8, 0, 2, 0.09)]
    )
    assert (tally.signals, tally.samples, tally.resets, tally.exceeds) == (2, 18, 1, 2)
    assert tally.worst_filtered_mps == pytest.approx(0.09)
    assert tally.worst_signal == "sys4-prn19-sig01"


def test_recorded_pppnav_fixture_parses_and_averages() -> None:
    fixture = FIXTURES / "captures-extra" / "PPPNAVB.bin"
    records = decode_records(read_frames(fixture), Log.PPPNAV)
    assert records
    epochs = ppp_epochs(records)
    assert len(epochs) == len(records)
    assert epochs[0].height == pytest.approx(
        records[0].real("hgt") + records[0].real("undulation")
    )
    assert all(isinstance(item.epoch, float) for item in epochs)
    fix = mean_fix(epochs, ppp_only=False)
    assert fix.epochs == len(records)
    assert -90 <= fix.latitude <= 90


def test_xyz_fallback_rejects_empty_capture() -> None:
    with pytest.raises(ValueError, match="fallback"):
        xyz_fallback(())


def test_xyz_fallback_requires_computed_position() -> None:
    coordinates = (("p_x", 4000000.0), ("p_y", 1000000.0), ("p_z", 4800000.0))
    valid = Record("BESTXYZ", (("p_sol_status", 0), ("pos_type", 16), *coordinates))
    invalid = Record(
        "BESTXYZ",
        (("p_sol_status", "INSUFFICIENT_OBS"), ("pos_type", "NONE"), *coordinates),
    )
    unknown = Record("BESTXYZ", coordinates)
    assert xyz_fallback((valid, invalid, unknown)).epochs == 1
    with pytest.raises(ValueError, match="no BESTXYZ positions"):
        xyz_fallback((invalid, unknown))


def test_precision_statistics_reports_scatter_and_p95() -> None:
    stats = precision_statistics([epoch(index) for index in range(10)])
    assert stats.epochs == 10
    assert stats.span_seconds == pytest.approx(9.0)
    assert stats.horizontal_scatter < 0.05
    assert stats.radius_p95 == pytest.approx(1.7308 * stats.horizontal_scatter)
    assert stats.mean_horizontal_sigma == pytest.approx(stats.min_horizontal_sigma)
    assert stats.improvement == pytest.approx(1.0)


def test_precision_statistics_rejects_empty() -> None:
    with pytest.raises(ValueError, match="no epochs"):
        precision_statistics([])


def test_cycle_fixes_delivers_running_stats() -> None:
    from examples.has_b2b_ppp_fix.cyclic import cycle_fixes

    seen: list[int] = []
    delivered = cycle_fixes(
        [epoch(index) for index in range(5)], lambda fix: seen.append(fix.index)
    )
    assert delivered == 5
    assert seen == [1, 2, 3, 4, 5]


def test_cycle_fixes_stops_when_callback_asks() -> None:
    from examples.has_b2b_ppp_fix.cyclic import cycle_fixes

    delivered = cycle_fixes(
        [epoch(index) for index in range(5)], lambda fix: fix.index >= 2
    )
    assert delivered == 2


def test_cycle_fixes_skips_non_ppp_by_default() -> None:
    from examples.has_b2b_ppp_fix.cyclic import cycle_fixes

    items = [epoch(0, pos_type=16), epoch(1)]
    assert cycle_fixes(items, lambda fix: False) == 1
    assert cycle_fixes(items, lambda fix: False, ppp_only=False) == 2


def test_cyclic_cli_replays_fixture(tmp_path: Path) -> None:
    import json

    from examples.has_b2b_ppp_fix.cyclic import main as cyclic_main

    destination = tmp_path / "cyclic.json"
    assert (
        cyclic_main(
            [
                "--replay",
                str(FIXTURES / "captures-extra" / "PPPNAVB.bin"),
                "--json",
                str(destination),
            ]
        )
        == 0
    )
    payload = json.loads(destination.read_text())
    assert payload["delivered"] == 1
    assert payload["running_mean"]["epochs"] == 1
    assert payload["precision"]["epochs"] == 1


def test_cyclic_cli_rejects_nonpositive_cycles() -> None:
    from examples.has_b2b_ppp_fix.cyclic import main as cyclic_main

    with pytest.raises(SystemExit):
        cyclic_main(["--cycles", "0"])


def test_stream_fixes_delivers_pushed_message_without_polling() -> None:
    from types import SimpleNamespace

    from examples.has_b2b_ppp_fix.cyclic import stream_fixes

    from um982py.errors import ResponseTimeout
    from um982py.messages import Message

    class PushedReceiver:
        def __init__(self, messages: list[Message]) -> None:
            self._messages = messages
            self.commands: list[str] = []

        def execute(
            self, command: object, *, timeout: float | None = None
        ) -> SimpleNamespace:
            self.commands.append(str(getattr(command, "text", command)))
            return SimpleNamespace(entries=())

        def receive(self, *, timeout: float | None = None) -> Message:
            if not self._messages:
                raise ResponseTimeout("drained")
            return self._messages.pop(0)

    receiver = PushedReceiver(
        list(read_frames(FIXTURES / "captures-extra" / "PPPNAVB.bin"))
    )
    seen: list[int] = []
    delivered = stream_fixes(
        receiver,
        lambda fix: seen.append(fix.index),
        cycles=1,
        cycle_seconds=1.0,
        timeout=1.0,
    )
    assert delivered == 1
    assert seen == [1]
    assert receiver.commands == ["LOGLISTA", "PPPNAVB 1", "UNLOG PPPNAVB"]


def test_cli_reports_help_and_missing_replay(tmp_path: Path) -> None:
    import subprocess
    import sys

    project = Path(__file__).resolve().parents[2]
    missing = tmp_path / "missing.bin"
    result = subprocess.run(
        [sys.executable, "-m", "examples.has_b2b_ppp_fix", "--replay", str(missing)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_cli_replays_recorded_pppnav(tmp_path: Path) -> None:
    from examples.has_b2b_ppp_fix.__main__ import main

    destination = tmp_path / "fix.json"
    assert (
        main(
            [
                "--replay",
                str(FIXTURES / "captures-extra" / "PPPNAVB.bin"),
                "--min-ppp",
                "1",
                "--json",
                str(destination),
            ]
        )
        == 0
    )
    import json

    payload = json.loads(destination.read_text())
    assert payload["fix"]["source"] in ("PPPNAV", "BESTXYZ")
    assert payload["corrections"]["b2b_blocks"] == 0
    assert "latitude" in payload["fix"]
    assert "precision" in payload
    assert payload["precision"]["epochs"] == payload["fix"]["epochs"]
