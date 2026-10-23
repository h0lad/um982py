"""Check the guided station setup and generated startup configuration."""

import base64
import os
import shlex
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from examples.ntrip_server.auth import Credentials
from examples.ntrip_server.setup import main
from examples.ntrip_server.station import Station

from tests.examples.test_ntrip_server import tls_files as tls_files


def test_private_upload_setup_creates_usable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "station with spaces"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    answers = iter(
        [
            "private",
            "upload",
            "TEST01",
            "42",
            "arp",
            "48.7",
            "9.3",
            "305.5",
            "ITRF2020",
            "2026.8",
            "reviewed report",
            "yes",
            "rover",
            "local",
            str(port),
        ]
    )
    secret = "this is a test password"  # noqa: S105
    passwords = iter((secret, secret, secret, secret))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 0
    station = Station.load(directory / "station.json")
    assert station.position_verified and station.height == 305.5
    for filename, username in (
        ("users.json", "rover"),
        ("source-users.json", "source"),
    ):
        path = directory / filename
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        token = base64.b64encode(f"{username}:{secret}".encode()).decode()
        assert Credentials.load(path).verify("Basic " + token) == username
    script = (directory / "start.sh").read_text()
    command = shlex.split(script.splitlines()[-1])
    assert command[0] == "exec"
    assert command[command.index("--mode") + 1] == "private"
    assert command[command.index("--source-users") + 1] == str(
        directory / "source-users.json"
    )
    assert secret not in script and secret not in capsys.readouterr().out
    assert stat.S_IMODE((directory / "start.sh").stat().st_mode) == 0o700
    project = Path(__file__).resolve().parents[2]
    environment = dict(os.environ, PYTHONPATH=str(project / "src"))
    process = subprocess.Popen(
        [str(directory / "start.sh")],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(
                    ("127.0.0.1", port), timeout=0.5
                ) as client:
                    client.sendall(
                        b"GET / HTTP/1.1\r\nHost: localhost\r\n"
                        b"Ntrip-Version: Ntrip/2.0\r\n\r\n"
                    )
                    assert b"401 Unauthorized" in client.recv(4096)
                    break
            except ConnectionRefusedError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail("generated startup script did not start the caster")
                time.sleep(0.05)
    finally:
        process.terminate()
        process.wait(timeout=3)


def test_unreviewed_coordinates_do_not_create_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "station"
    answers = iter(
        [
            "public",
            "receiver",
            "",
            "",
            "arp",
            "48.7",
            "9.3",
            "305.5",
            "ITRF2020",
            "2026.8",
            "report",
            "no",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 1
    assert not directory.exists()


def test_internet_setup_validates_tls_and_saves_the_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tls_files: tuple[Path, Path]
) -> None:
    directory = tmp_path / "station"
    cert, key = tls_files
    answers = iter(
        [
            "public",
            "receiver",
            "",
            "",
            "arp",
            "48.7",
            "9.3",
            "305.5",
            "ITRF2020",
            "2026.8",
            "report",
            "yes",
            "",
            "internet",
            "2101",
            str(cert),
            str(key),
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 0
    command = shlex.split((directory / "start.sh").read_text().splitlines()[-1])
    assert command[command.index("--bind") + 1] == "0.0.0.0"  # noqa: S104
    assert command[command.index("--tls-cert") + 1] == str(cert)
    assert command[command.index("--tls-key") + 1] == str(key)


def test_existing_directory_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_marker_coordinates_are_transferred_to_arp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "station"
    answers = iter(
        [
            "public",
            "receiver",
            "",
            "",
            "marker",
            "48",
            "9",
            "300",
            "1.25",
            "0",
            "0",
            "ITRF2020",
            "2026.0",
            "report",
            "yes",
            "",
            "local",
            "2101",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 0
    station = Station.load(directory / "station.json")
    assert station.latitude == pytest.approx(48, abs=1e-9)
    assert station.longitude == pytest.approx(9, abs=1e-9)
    assert station.height == pytest.approx(301.25, abs=1e-5)
    assert "Calculated ARP" in capsys.readouterr().out


def test_setup_offers_survey_when_coordinates_are_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "station"
    answers = iter(["public", "receiver", "", "", "not-yet"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(sys, "argv", ["setup", "--directory", str(directory)])
    assert main() == 1
    output = capsys.readouterr().out
    assert "examples.base_station_survey" in output
    assert "approximate" in output
    assert not directory.exists()
