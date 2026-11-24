import argparse
from unittest.mock import Mock

from examples._console import add_reliability_arguments, apply_reliability


def test_reliability_arguments_apply_rtk_and_adr() -> None:
    parser = argparse.ArgumentParser()
    add_reliability_arguments(parser)
    args = parser.parse_args(["--rtk-reliability", "2", "--adr-reliability", "1"])
    receiver = Mock()

    assert apply_reliability(receiver, args) is True
    assert receiver.execute.call_args.args[0].text == "CONFIG RTK RELIABILITY 2 1"


def test_reliability_arguments_can_set_only_adr() -> None:
    parser = argparse.ArgumentParser()
    add_reliability_arguments(parser)
    args = parser.parse_args(["--adr-reliability", "4"])
    receiver = Mock()

    assert apply_reliability(receiver, args) is True
    assert receiver.execute.call_args.args[0].text == "CONFIG RTK RELIABILITY 3 4"


def test_reliability_arguments_do_nothing_by_default() -> None:
    parser = argparse.ArgumentParser()
    add_reliability_arguments(parser)
    args = parser.parse_args([])
    receiver = Mock()

    assert apply_reliability(receiver, args) is False
    receiver.execute.assert_not_called()
