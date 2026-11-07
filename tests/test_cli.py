import runpy
from pathlib import Path
from types import SimpleNamespace
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
        patch("um982py.cli.enable_augmentation") as augmentation,
        patch("um982py.cli._run_action", return_value={"connected": True}),
    ):
        assert main(["--port", "tcp://127.0.0.1:4001", "version"]) == 0
    factory.assert_called_once_with("tcp://127.0.0.1:4001", 115200, timeout=3.0)
    augmentation.assert_not_called()
    assert '"connected": true' in capsys.readouterr().out


def test_augmentation_is_explicit_and_reports_refusals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = SimpleNamespace(rejected=(("sbas", "unsupported"),))
    with (
        patch.object(Receiver, "connect", return_value=Receiver(ReplayTransport())),
        patch("um982py.cli.enable_augmentation", return_value=state) as augmentation,
        patch("um982py.cli._run_action", return_value={}),
    ):
        assert main(["--augment", "version"]) == 0
    augmentation.assert_called_once()
    assert "augmentation refused: sbas" in capsys.readouterr().err


def test_cli_recording_is_flushed_before_a_failed_action(tmp_path: Path) -> None:
    path = tmp_path / "capture.bin"
    transport = ReplayTransport(chunk=100)
    transport.pending.extend(b"receiver data")

    def fail_after_read(receiver: Receiver, *args: object) -> None:
        assert receiver.transport.read(100, 1) == b"receiver data"
        assert path.read_bytes() == b"receiver data"
        raise TransportError("receiver disconnected")

    with (
        patch.object(Receiver, "connect", return_value=Receiver(transport)),
        patch("um982py.cli._run_action", side_effect=fail_after_read),
    ):
        assert main(["--record", str(path), "version"]) == 2
    assert path.read_bytes() == b"receiver data"
    assert transport.closed


def test_cli_does_not_continue_after_augmentation_failure() -> None:
    transport = ReplayTransport()
    with (
        patch.object(Receiver, "connect", return_value=Receiver(transport)),
        patch("um982py.cli.enable_augmentation", side_effect=TransportError("lost")),
        patch("um982py.cli._run_action") as action,
    ):
        assert main(["--augment", "version"]) == 2
    action.assert_not_called()
    assert transport.closed
