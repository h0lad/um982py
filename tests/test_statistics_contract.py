"""Regression checks for the shared correlation implementation."""

import math

import pytest

from um982py.corrections import finite as correction_finite
from um982py.geodesy import SPEED_OF_LIGHT
from um982py.science_experiments import C
from um982py.science_experiments import correlation as experiment_correlation
from um982py.stats import correlation, finite


def test_correlation_minimum_contracts() -> None:
    assert correlation([1, 2], [3, 4]) is None
    assert correlation([1, 2], [3, 4], minimum_samples=2) == pytest.approx(1)
    assert experiment_correlation([1, 2], [3, 4]) == pytest.approx(1)
    assert experiment_correlation([1, 1], [3, 4]) is None
    with pytest.raises(ValueError, match="at least two paired"):
        experiment_correlation([1], [2])
    with pytest.raises(ValueError, match="minimum_samples"):
        correlation([1, 2], [1, 2], minimum_samples=1)


def test_finite_helper_and_constant_are_shared() -> None:
    assert correction_finite is finite
    assert C == SPEED_OF_LIGHT
    with pytest.raises(ValueError, match="finite"):
        correction_finite(math.nan)


@pytest.mark.parametrize("failure", [TypeError("unexpected"), KeyboardInterrupt()])
def test_receiver_is_closed_if_setup_fails(failure: BaseException) -> None:
    from argparse import Namespace
    from unittest.mock import patch

    from um982py.capture import open_receiver

    args = Namespace(port="fake", baud=921600, augment=True, replay=None)
    with (
        patch("um982py.console_capture.Receiver.connect") as connect,
        patch("um982py.capture.enable_augmentation", side_effect=failure),
        pytest.raises(type(failure)),
    ):
        open_receiver(args)
    connect.return_value.close.assert_called_once_with()


def test_recoverable_augmentation_warning_keeps_receiver_open() -> None:
    from argparse import Namespace
    from unittest.mock import patch

    from um982py.capture import open_receiver

    args = Namespace(port="fake", baud=921600, augment=True, replay=None)
    with (
        patch("um982py.console_capture.Receiver.connect") as connect,
        patch("um982py.capture.enable_augmentation", side_effect=ValueError("no PPP")),
    ):
        assert open_receiver(args) is connect.return_value
    connect.return_value.close.assert_not_called()
