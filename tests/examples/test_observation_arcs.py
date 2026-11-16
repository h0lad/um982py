"""Carrier-arc identity checks for the N4 RANGE tracking status."""

from __future__ import annotations

from examples._observation_arcs import CarrierState, continuous

L2_HZ = 1227.60e6


def state(epoch: float, *, l2c: bool) -> CarrierState:
    return CarrierState(
        epoch=epoch,
        frequency_hz=L2_HZ,
        signal=9,
        lock_seconds=epoch + 1.0,
        phase_cycles=epoch * 1000.0,
        doppler_hz=1000.0,
        l2c_flag=l2c,
    )


def test_same_signal_and_frequency_arc_is_continuous() -> None:
    assert continuous(state(0.0, l2c=True), state(1.0, l2c=True), max_gap=2.0)


def test_l2c_to_l2p_switch_breaks_the_arc() -> None:
    """L2C and L2P(Y) share carrier frequency and signal ID 9 (N4 interface guide)."""
    assert not continuous(state(0.0, l2c=True), state(1.0, l2c=False), max_gap=2.0)
    assert not continuous(state(0.0, l2c=False), state(1.0, l2c=True), max_gap=2.0)


def test_default_legacy_state_has_no_l2c_flag() -> None:
    legacy = CarrierState(0.0, L2_HZ, 9, 1.0, 0.0, 1000.0)
    assert legacy.l2c_flag is False
    assert continuous(legacy, state(1.0, l2c=False), max_gap=2.0)
