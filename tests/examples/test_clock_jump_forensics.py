"""Checks clock-jump consensus against labelled steps and isolated slips."""

from dataclasses import replace

import pytest
from examples.clock_jump_forensics import clock_residuals, detect_clock_jumps

from tests.examples._specialist import sample


def test_one_millisecond_step_is_recovered_in_code_and_carrier() -> None:
    before = [sample(0, prn=p, code=2e7, phase=2e7) for p in range(1, 7)]
    after = [
        sample(1, prn=p, code=2e7 + 299792.458, phase=2e7 + 299792.458)
        for p in range(1, 7)
    ]
    result = detect_clock_jumps(before, after)
    assert result is not None
    assert result.code_jump_m == pytest.approx(299792.458, abs=1e-8)
    assert result.phase_jump_m == pytest.approx(299792.458, abs=1e-8)
    assert result.classification == "code_and_phase"


def test_single_satellite_phase_step_does_not_become_a_clock_jump() -> None:
    before = [sample(0, prn=p) for p in range(1, 7)]
    after = [sample(1, prn=p, phase=100 + (1e6 if p == 1 else 0)) for p in range(1, 7)]
    assert detect_clock_jumps(before, after) is None


def test_code_only_receiver_resteering_is_distinguished() -> None:
    before = [sample(0, prn=p) for p in range(1, 5)]
    after = [sample(1, prn=p, code=1e6) for p in range(1, 5)]
    result = detect_clock_jumps(before, after)
    assert result is not None and result.classification == "code_only"
    assert result.phase_jump_m is None


def test_duplicate_satellites_cannot_manufacture_consensus() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        detect_clock_jumps([sample(0)] * 4, [sample(1)] * 4)


def test_lock_reset_removes_a_satellite_from_consensus() -> None:
    before = [sample(0, prn=p) for p in range(1, 5)]
    after = [sample(1, prn=p, code=1e6) for p in range(1, 5)]
    after[0] = replace(after[0], lock_seconds=0.01)
    assert detect_clock_jumps(before, after) is None
    assert len(clock_residuals(before, after)[0]) == 3


def test_four_unshared_satellites_do_not_count_as_a_tested_clock_interval() -> None:
    before = [sample(0, prn=p) for p in range(1, 5)]
    after = [sample(1, prn=p) for p in range(5, 9)]
    assert clock_residuals(before, after) == ((), ())
