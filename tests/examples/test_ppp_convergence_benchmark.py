"""Tests for ppp_convergence_benchmark helpers."""

from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest
from examples.ppp_convergence_benchmark import percentile


def test_collection_rejects_non_ppp_and_duplicate_epochs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examples.ppp_convergence_benchmark import __main__ as cli

    from um982py import Receiver
    from um982py.commands import Log
    from um982py.commands.core import Command
    from um982py.errors import ResponseTimeout
    from um982py.messages.enums import PositionType, SolutionStatus
    from um982py.messages.navigation import BestNavigation
    from um982py.protocol.ascii import parse_ascii
    from um982py.receiver_models import LogList

    data = Path("tests/fixtures/bodies/BESTNAVA.bin").read_bytes()
    base = BestNavigation.from_record(Log.BESTNAV.decode(parse_ascii(data)))
    nav = replace(
        base,
        solution_status=SolutionStatus.SOL_COMPUTED,
        position_type=PositionType.PPP,
        epoch_gps_seconds=100.0,
    )
    inputs = iter(
        [
            replace(nav, position_type=PositionType.SINGLE),
            nav,
            nav,
            replace(nav, epoch_gps_seconds=110.0),
        ]
    )

    commands = []

    class FakeReceiver:
        def __enter__(self) -> FakeReceiver:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            pass

        def execute(self, command: Command[object]) -> LogList:
            commands.append(command.text)
            return LogList(())

        def receive(self, timeout: float) -> BestNavigation:
            try:
                return next(inputs)
            except StopIteration:
                raise ResponseTimeout() from None

    monkeypatch.setattr(Receiver, "connect", lambda *args, **kwargs: FakeReceiver())
    monkeypatch.setattr(cli, "_to_bestnav", lambda message: message)
    args = Namespace(
        horizontal_limit=1.0,
        vertical_limit=1.0,
        max_epoch_age=2.0,
        min_epochs=2,
        hold_seconds=0.0,
        max_gap=2.0,
        duration=0.01,
        interval=1.0,
        port="unused",
        baud=115200,
        timeout=0.001,
        trust_host_clock=False,
        reference_ecef=None,
    )
    epochs, first_fix, convergence, counts = cli._collect_epochs(args)
    assert commands == ["LOGLISTA", "BESTNAVA 1", "UNLOG BESTNAVA"]
    assert len(epochs) == 2
    assert first_fix is not None and convergence is None
    assert counts == {
        "accepted": 2,
        "non_ppp_or_invalid": 1,
        "duplicate_or_reversed": 1,
        "gaps": 1,
    }


def test_percentile_median() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50.0) == pytest.approx(3.0, abs=1e-12)


def test_percentile_95th() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 95.0) == pytest.approx(4.8, abs=1e-12)


def test_percentile_empty() -> None:
    assert percentile([], 50.0) is None


def test_percentile_single() -> None:
    assert percentile([42.0], 50.0) == pytest.approx(42.0, abs=1e-12)


def test_reference_error_uses_the_geodetic_frame_of_the_reference() -> None:
    from examples.ppp_convergence_benchmark import _reference_error

    from um982py.geodesy import ecef_from_geodetic

    reference = ecef_from_geodetic(52.0, 13.0, 100.0)
    east, north, up = _reference_error(ecef_from_geodetic(52.0, 13.0, 101.0), reference)
    assert (east, north) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert up == pytest.approx(1.0, abs=1e-6)
