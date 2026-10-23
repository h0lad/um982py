import runpy
from unittest.mock import patch

import pytest

from conftest import ReplayTransport
from um982py import Receiver
from um982py.cli import _json, main
from um982py.errors import TransportError


def test_cli_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(Receiver, "connect", side_effect=TransportError("gone")):
        assert main(["version"]) == 2
    assert "gone" in capsys.readouterr().err
    with patch.object(Receiver, "connect", side_effect=KeyboardInterrupt):
        assert main(["version"]) == 130
    with pytest.raises(SystemExit):
        main(["monitor", "--count", "0"])
    with pytest.raises(TypeError):
        _json(object())


def test_module_entry_point() -> None:
    with patch("um982py.cli.main", return_value=0), pytest.raises(SystemExit) as caught:
        runpy.run_module("um982py", run_name="__main__")
    assert caught.value.code == 0


def test_cli_accepts_tcp_target(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(
            Receiver, "connect", return_value=Receiver(ReplayTransport())
        ) as factory,
        patch("um982py.cli.enable_augmentation"),
        patch("um982py.cli._run_action", return_value={"connected": True}),
    ):
        assert main(["--port", "tcp://127.0.0.1:4001", "version"]) == 0
    factory.assert_called_once_with("tcp://127.0.0.1:4001", 115200, timeout=3.0)
    assert '"connected": true' in capsys.readouterr().out
