"""Checks Doppler velocity against a hand-computed observation table."""

import json
import math
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from struct import pack_into

import pytest
from examples._gps_motion import _observer, _receiver_comparison
from examples.doppler_velocity import wave_parameters
from examples.doppler_velocity.receiver_state import main as receiver_state

from tests.examples._specialist import TRUTH
from tests.test_protocol import binary
from um982py.capture import decode_records, read_frames, record_epoch
from um982py.commands import Log
from um982py.experimental.gps_motion import RateMeasurement, solve_velocity
from um982py.messages import Record


def test_native_doppler_report_joins_by_payload_epoch(tmp_path: Path) -> None:
    capture, output = tmp_path / "velocity.bin", tmp_path / "velocity.json"
    payload = bytearray(120)
    pack_into("<H2xI", payload, 0, 2400, 123000)
    pack_into("<7d", payload, 16, 1.0, 2.0, 3.0, 0.25, 0.25, 0.5, 0.75)
    first = binary(bytes(payload), 95)
    pack_into("<I", payload, 4, 123100)
    second = binary(bytes(payload), 95)
    reference = bytearray(112)
    pack_into("<II3d3f", reference, 44, 0, 8, 1.0, 2.0, 3.125, 0.25, 0.5, 0.625)
    capture.write_bytes(binary(bytes(reference), 240) + first + second)

    assert receiver_state(["--replay", str(capture), "--json", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["matched_epochs"] == 1
    assert result["max_velocity_difference_mps"] == 0.125
    assert result["max_axis_std_difference_mps"] == 0.125
    matched, unmatched = result["epochs"]
    assert matched["clock_drift_mps"] == -0.25
    assert matched["velocity_std_ecef_mps"] == [0.25, 0.5, 0.75]
    assert matched["bestnavxyz_comparison"]["axis_std_differences_mps"] == [0, 0, 0.125]
    assert unmatched["bestnavxyz_comparison"] is None


def test_observer_ignores_invalid_and_uncomputed_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def position(epoch: float, status: str, x: float) -> Record:
        return Record(
            "BESTXYZ",
            (
                ("epoch", epoch),
                ("p_sol_status", status),
                ("p_x", x),
                ("p_y", 0.0),
                ("p_z", 0.0),
            ),
        )

    monkeypatch.setattr("examples._gps_motion.record_epoch", lambda r: r.real("epoch"))
    records = [
        position(1, "INSUFFICIENT_OBS", 6378137),
        position(1, "SOL_COMPUTED", 0),
        position(1.5, "SOL_COMPUTED", 6378137),
    ]
    assert _observer(Namespace(observer=None), records, 1) == (6378137, 0, 0)
    with pytest.raises(ValueError, match="computed BESTXYZ"):
        _observer(Namespace(observer=None), records[:2], 1)
    with pytest.raises(ValueError, match="finite plausible"):
        _observer(Namespace(observer=[0.0, 0.0, 0.0]), [], 1)


def measurements() -> list[RateMeasurement]:
    """Read the frozen signed-rate table without synthesizing from a solution."""
    return [
        RateMeasurement(i + 1, tuple(direction), tuple(velocity), rate, clock, i + 1)
        for i, (direction, velocity, rate, clock) in enumerate(
            zip(
                TRUTH["directions"],
                TRUTH["satellite_velocity_mps"],
                TRUTH["range_rate_mps"],
                TRUTH["satellite_clock_mps"],
                strict=True,
            )
        )
    ]


def test_recovers_independently_tabulated_velocity_and_clock() -> None:
    result = solve_velocity(measurements())
    assert result.velocity == pytest.approx(TRUTH["velocity_mps"], abs=1e-10)
    assert result.clock_mps == pytest.approx(TRUTH["clock_mps"], abs=1e-10)
    assert result.residual_rms_mps < 1e-10


def test_satellite_motion_and_clock_corrections_are_required() -> None:
    wrong = [
        replace(item, satellite_velocity=(0, 0, 0), satellite_clock_mps=0)
        for item in measurements()
    ]
    result = solve_velocity(wrong)
    assert abs(result.velocity[0] - TRUTH["velocity_mps"][0]) > 100


@pytest.mark.parametrize("count", [0, 1, 3])
def test_underdetermined_sky_has_no_velocity(count: int) -> None:
    with pytest.raises(ValueError, match="four"):
        solve_velocity(measurements()[:count])


def test_singular_geometry_is_rejected() -> None:
    with pytest.raises(ValueError, match="singular"):
        solve_velocity(
            [replace(item, line_of_sight=(1, 0, 0)) for item in measurements()]
        )


def test_duplicate_signals_cannot_count_as_independent_satellites() -> None:
    with pytest.raises(ValueError, match="distinct"):
        solve_velocity([replace(item, prn=1) for item in measurements()])


def test_receiver_speed_comparison_is_time_bounded_and_excludes_invalid_fixes() -> None:
    path = Path("tests/fixtures/captures/DOPPVELA.bin")
    record = decode_records(read_frames(path), Log.DOPPVEL)[0]
    epoch = record_epoch(record)
    result = _receiver_comparison(
        epoch, (1.0, 2.0, 3.0), (6378137.0, 0.0, 0.0), [record], tolerance=0.1
    )
    assert result is not None
    assert result["horizontal_difference_mps"] == pytest.approx(
        math.hypot(2, 3) - record.real("hor_spd")
    )
    assert result["vertical_difference_mps"] == pytest.approx(
        1 - record.real("vert_spd")
    )
    assert (
        _receiver_comparison(
            epoch + 1, (1, 2, 3), (6378137, 0, 0), [record], tolerance=0.1
        )
        is None
    )
    invalid = replace(
        record,
        entries=tuple(
            (k, "INSUFFICIENT_OBS" if k == "v_sol_status" else v)
            for k, v in record.entries
        ),
    )
    assert (
        _receiver_comparison(
            epoch, (1, 2, 3), (6378137, 0, 0), [invalid], tolerance=0.1
        )
        is None
    )
    wrong_type = replace(
        record,
        entries=tuple((k, "NONE" if k == "vel_type" else v) for k, v in record.entries),
    )
    assert (
        _receiver_comparison(
            epoch, (1, 2, 3), (6378137, 0, 0), [wrong_type], tolerance=0.1
        )
        is None
    )


def heave_velocity(
    amplitude: float, period: float, count: int, step: float
) -> list[float]:
    """Vertical velocity of one harmonic wave sampled at ``step`` seconds."""
    omega = 2.0 * math.pi / period
    return [
        amplitude * omega * math.cos(omega * index * step) for index in range(count)
    ]


def test_harmonic_heave_recovers_significant_height_and_period() -> None:
    step = 0.25
    parameters = wave_parameters(heave_velocity(0.5, 8.0, 1024, step), step)
    assert parameters.significant_height_m == pytest.approx(
        2.0 * math.sqrt(2.0) * 0.5, rel=0.01
    )
    assert parameters.peak_period_s == pytest.approx(8.0, rel=0.01)
    assert parameters.mean_period_s == pytest.approx(8.0, rel=0.01)
    assert parameters.sample_count == 1024


def test_a_constant_vertical_velocity_is_not_a_wave() -> None:
    parameters = wave_parameters([0.05] * 256, 0.25)
    assert parameters.significant_height_m == pytest.approx(0.0, abs=1e-12)
    assert math.isnan(parameters.mean_period_s)


def test_wave_parameters_reject_short_or_invalid_series() -> None:
    with pytest.raises(ValueError, match="eight samples"):
        wave_parameters([0.0] * 7, 1.0)
    with pytest.raises(ValueError, match="interval"):
        wave_parameters([0.0] * 8, 0.0)
    with pytest.raises(ValueError, match="finite"):
        wave_parameters([0.0] * 7 + [math.nan], 1.0)
