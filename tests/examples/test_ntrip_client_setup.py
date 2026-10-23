"""Check guided rover setup and generated commands without network access."""

import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from examples.ntrip_client.__main__ import _parser, _password
from examples.ntrip_client.setup import main


def test_rtk2go_setup_has_expected_settings_and_no_password_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "rover config"
    answers = iter(
        [
            "http://rtk2go.com:2101/Weinstadt",
            "",
            "",
            "rover@valid.invalid",
            "",
            "",
            "",
            "yes",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 0
    path = directory / "start.sh"
    script = path.read_text()
    command = shlex.split(script.splitlines()[-1])
    parsed = _parser().parse_args(command[4:])
    assert parsed.caster == "http://rtk2go.com:2101/Weinstadt"
    assert parsed.ntrip_version == 1 and parsed.username == "rover@valid.invalid"
    assert parsed.duration == 60 and not parsed.no_gga
    assert "NTRIP_PASSWORD=none" in script
    assert "without encryption" in capsys.readouterr().out
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    subprocess.run(["/bin/sh", "-n", str(path)], check=True)


def test_password_setup_prompts_at_run_time_and_never_stores_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "private"
    answers = iter(
        [
            "https://caster.invalid:443/BASE",
            "2",
            "password",
            "rover",
            "/dev/ttyUSB1",
            "115200",
            "300",
            "no",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 0
    script = (directory / "start.sh").read_text()
    command = shlex.split(script.splitlines()[-1])
    parsed = _parser().parse_args(command[4:])
    assert parsed.no_gga and parsed.baud == 115200 and parsed.duration == 300
    assert "getpass.getpass" in script and "NTRIP_PASSWORD" in script
    monkeypatch.setenv("NTRIP_PASSWORD", "synthetic credential")
    assert _password(parsed) == "synthetic credential"
    assert "synthetic credential" not in script
    subprocess.run(["/bin/sh", "-n", str(directory / "start.sh")], check=True)


def test_setup_refuses_to_overwrite_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
