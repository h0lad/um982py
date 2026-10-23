"""Checks triple-frequency cancellation against analytic geometry and TEC terms."""

import json
from pathlib import Path

import pytest
from examples.triple_frequency_closure import closure_coefficients, frequency_closures
from examples.triple_frequency_closure.__main__ import main

from tests.examples._new_api import observation, record, wire

FREQUENCIES = (1575.42e6, 1227.60e6, 1176.45e6)


def trio(epoch: int, *, step: float = 0, reset: bool = False) -> list[bytes]:
    """Assign a moving geometry, varying dispersive delay and one phase-only step."""
    return [
        observation(
            signal=signal,
            frequency=f,
            l2c=int(signal == 9),
            code=20_000_000 + 1234 * epoch + (10 + epoch) * (FREQUENCIES[0] / f) ** 2,
            phase=20_000_000
            + 1234 * epoch
            - (10 + epoch) * (FREQUENCIES[0] / f) ** 2
            + (step if signal == 0 else 0),
            lock=1 if reset else 100 + epoch,
        )
        for signal, f in zip((0, 9, 14), FREQUENCIES, strict=True)
    ]


def test_closed_form_null_vector_and_noise_gain() -> None:
    assert closure_coefficients((1, 2, 3)) == pytest.approx((1, -32 / 5, 27 / 5))
    weights = closure_coefficients(FREQUENCIES)
    assert sum(weights) == pytest.approx(0, abs=1e-14)
    assert sum(
        w * (FREQUENCIES[0] / f) ** 2 for w, f in zip(weights, FREQUENCIES, strict=True)
    ) == pytest.approx(0, abs=1e-14)


def test_geometry_and_first_order_ionosphere_cancel_but_known_step_remains() -> None:
    rows = frequency_closures(
        [record(i, trio(i, step=0.025 if i == 2 else 0)) for i in range(3)],
        threshold_m=0.02,
    )
    assert [row.code_closure_m for row in rows] == pytest.approx([0, 0, 0], abs=1e-7)
    assert rows[1].phase_increment_m == pytest.approx(0, abs=1e-7)
    assert rows[2].phase_increment_m == pytest.approx(0.025, abs=1e-7)
    assert rows[2].threshold_exceeded
    assert rows[0].phase_increment_m is None
    assert rows[0].independent_equal_noise_gain > 5


def test_lock_gap_and_missing_trio_start_new_arcs() -> None:
    values = [
        record(0, trio(0)),
        record(1, trio(1, reset=True)),
        record(5, trio(5)),
        record(6, []),
        record(7, trio(7)),
    ]
    rows = frequency_closures(values)
    assert [r.arc_start_reason for r in rows] == [
        "start",
        "lock_reset",
        "gap",
        "missing_trio",
    ]
    assert [r.arc for r in rows] == [1, 2, 3, 4]
    assert all(r.phase_increment_m is None for r in rows)


def test_wrong_l2c_flag_cannot_complete_a_trio() -> None:
    rows = record(0, trio(0))
    assert frequency_closures([rows], l2c_flag=0) == ()


@pytest.mark.parametrize("frequencies", [(1, 1, 2), (0, 2, 3), (float("nan"), 2, 3)])
def test_invalid_frequency_trios_rejected(
    frequencies: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError):
        closure_coefficients(frequencies)


def test_duplicate_epoch_cannot_manufacture_an_increment() -> None:
    value = record(0, trio(0))
    with pytest.raises(ValueError, match="increase strictly"):
        frequency_closures([value, value])


def test_cli_replay_and_missing_inputs(tmp_path: Path) -> None:
    path, output = tmp_path / "trio.bin", tmp_path / "out.json"
    path.write_bytes(b"".join(wire(i, trio(i)) for i in range(3)))
    assert main(["--replay", str(path), "--json", str(output)]) == 0
    assert json.loads(output.read_text())["tested_increments"] == 2
    assert main(["--replay", str(path), "--l2c-flag", "0", "--json", str(output)]) == 1
    missing = json.loads(output.read_text())
    assert missing["next_step"]
    assert {item["signal"] for item in missing["signal_inventory"]} == {0, 9, 14}


def test_fdma_carriers_are_per_satellite_and_channel_changes_restart_arcs() -> None:
    def rows(channel: int, epoch: int) -> list[bytes]:
        frequencies = (
            (1602 + 0.5625 * (channel - 7)) * 1e6,
            (1246 + 0.4375 * (channel - 7)) * 1e6,
            1202.025e6,
        )
        return [
            observation(
                system=1,
                signal=signal,
                channel=channel,
                frequency=f,
                lock=100 + epoch,
                code=20_000_000 + (1575.42e6 / f) ** 2,
                phase=20_000_000 - (1575.42e6 / f) ** 2,
            )
            for signal, f in zip((0, 5, 6), frequencies, strict=True)
        ]

    result = frequency_closures(
        [record(0, rows(0, 0)), record(1, rows(0, 1)), record(2, rows(13, 2))],
        system=1,
        signals=(0, 5, 6),
    )
    assert result[0].frequencies_hz[0] == 1598062500
    assert result[1].phase_increment_m == pytest.approx(0, abs=1e-7)
    assert result[2].arc_start_reason == "frequency_change"
    assert result[2].phase_increment_m is None


def test_published_esa_gamma_solution_matches_coefficients() -> None:
    first, second, third = FREQUENCIES
    g12, g13 = (first / second) ** 2, (first / third) ** 2
    published = (g12 - g13, -(1 - g13), 1 - g12)
    reference = tuple(value / published[0] for value in published)
    assert closure_coefficients(FREQUENCIES) == pytest.approx(reference, abs=1e-14)
