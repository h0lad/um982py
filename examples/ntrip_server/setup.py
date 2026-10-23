"""Set up a reference station and create a reusable start script."""

import argparse
import getpass
import json
import math
import os
import re
import shlex
import ssl
import sys
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from examples.coordinate_frames import Baseline, Geodetic, antenna_position
from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.station import Station


def ask(label: str, default: str | None = None) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("Please enter a value.")


def choice(label: str, choices: tuple[str, ...], default: str) -> str:
    while True:
        answer = ask(f"{label} ({'/'.join(choices)})", default).lower()
        if answer in choices:
            return answer
        print(f"Choose one of: {', '.join(choices)}")


def number(label: str, low: float, high: float, default: str | None = None) -> float:
    while True:
        try:
            value = float(ask(label, default))
            if math.isfinite(value) and low <= value <= high:
                return value
        except ValueError:
            pass
        print(f"Enter a number from {low:g} to {high:g}.")


def integer(label: str, low: int, high: int, default: str) -> int:
    while True:
        value = number(label, low, high, default)
        if value.is_integer():
            return int(value)
        print("Enter a whole number.")


def account(label: str, *, fixed_username: str | None = None) -> dict[str, str]:
    while True:
        username = fixed_username or ask(f"{label} username", "rover")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
            break
        print("Use 1-64 letters, digits, dots, underscores or hyphens.")
    while True:
        password = getpass.getpass(f"{label} password (at least 16 bytes): ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords do not match; try again.")
            continue
        try:
            users = {username: hash_password(password)}
            Credentials(users)
            return users
        except ValueError as error:
            print(error)


def private_file(path: Path, content: str, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path("ntrip-station"),
        help="new directory for the station files (default: ntrip-station)",
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        parser.error(f"directory already exists: {directory}; choose a new directory")
    print("NTRIP station setup. Run from the lib/um982py project directory.")
    print("You need a reviewed survey of the fixed antenna or its ground marker.")
    print("The ARP is the antenna reference point, not its electrical phase centre.")
    mode = choice("Rover access", ("public", "private"), "public")
    source = choice("Correction source", ("receiver", "upload"), "receiver")
    print("Mountpoint is the stream name clients select (for example BASE01).")
    while True:
        mountpoint = ask("Mountpoint", "BASE01")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", mountpoint) and mountpoint != "healthz":
            break
        print("Use 1-64 letters, digits, underscores or hyphens; healthz is reserved.")
    if source == "upload":
        print("The station ID and ARP must match the uploaded RTCM 1005 message.")
    else:
        print("Choose an RTCM station ID from 0 to 4095, unique among nearby bases.")
    station_id = integer("RTCM station ID", 0, 4095, "42")
    point = choice(
        "Survey coordinates refer to", ("arp", "marker", "not-yet"), "not-yet"
    )
    if point == "not-yet":
        print("To obtain a reviewed station position:")
        print("1. Install the antenna and measure marker-to-ARP offsets.")
        print("2. Obtain an approximate position with:")
        print(
            "   python -m examples.base_station_survey --port /dev/ttyUSB0 "
            "--baud 921600 --json rough-position.json"
        )
        print("   This result is approximate, not a reviewed station coordinate.")
        print("3. Record 24 hours and export RINEX using the command in SURVEY.md.")
        print("4. Submit the RINEX file to the online Canadian CSRS-PPP service:")
        print(
            "   https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp.php?locale=en"
        )
        print("5. Review the solution and repeat on an independent day.")
        print("6. Rerun this setup with the reviewed marker or ARP coordinates.")
        print("Full instructions: examples/ntrip_server/SURVEY.md")
        return 1
    print("Enter decimal degrees: north/east positive; south/west negative.")
    print("Height is ellipsoidal (h), in metres; do not enter height above sea level.")
    latitude = number(f"{point.upper()} latitude (decimal degrees)", -90, 90)
    longitude = number(f"{point.upper()} longitude (decimal degrees)", -180, 180)
    height = number(f"{point.upper()} ellipsoidal height (metres)", -1000, 10000)
    if point == "marker":
        print("Measure the offsets from the marker to the ARP in metres.")
        print("Up is vertical; east and north are signed horizontal offsets.")
        up = number("Up (height of ARP above marker)", 0, 100)
        east = number("East offset", -100, 100, "0")
        north = number("North offset", -100, 100, "0")
        arp = antenna_position(
            Geodetic(latitude, longitude, height),
            Baseline(east=east, north=north, up=up),
        )
        latitude, longitude, height = arp.latitude, arp.longitude, arp.height
        print(
            f"Calculated ARP: {latitude:.9f}, {longitude:.9f}, "
            f"{height:.4f} m ellipsoidal"
        )
    print("Copy the reference frame and coordinate epoch from the reviewed solution.")
    print("The epoch is a decimal year (for example 2026.8), not a date or GPS week.")
    frame = ask("Reference frame (for example ITRF2020)")
    epoch = number("Coordinate epoch (decimal year)", 1980, 2100)
    report = ask("Survey report name or source")
    if (
        choice("Are these surveyed ARP coordinates reviewed", ("yes", "no"), "no")
        != "yes"
    ):
        print("Setup stopped. Review the ARP coordinates before starting a station.")
        return 1
    station = Station(
        mountpoint, station_id, latitude, longitude, height, frame, epoch, report, True
    )
    rover = account("Rover") if mode == "private" else None
    publisher = (
        account("Source", fixed_username="source") if source == "upload" else None
    )
    port = ask("Receiver serial port", "/dev/ttyUSB0") if source == "receiver" else None
    print("Local is available only on this computer; internet binds all interfaces.")
    exposure = choice("Network access", ("local", "internet"), "local")
    bind = "127.0.0.1" if exposure == "local" else "0.0.0.0"  # noqa: S104
    listen_port = integer("NTRIP port", 1, 65535, "2101")
    cert = key = None
    if exposure == "internet":
        while True:
            cert = Path(ask("TLS certificate file (full chain)")).expanduser().resolve()
            key = Path(ask("TLS private key file")).expanduser().resolve()
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert, key)
                break
            except (OSError, ssl.SSLError) as error:
                print(f"Could not load certificate and key: {error}")
    command = [
        sys.executable,
        "-m",
        "examples.ntrip_server",
        "--mode",
        mode,
        "--station",
        str(directory / "station.json"),
        "--bind",
        bind,
        "--listen-port",
        str(listen_port),
    ]
    if rover is not None:
        command += ["--users", str(directory / "users.json")]
    if publisher is not None:
        command += ["--source-users", str(directory / "source-users.json")]
    if port is not None:
        command += ["--port", port]
    if cert is not None and key is not None:
        command += ["--tls-cert", str(cert), "--tls-key", str(key)]
    project = Path(__file__).resolve().parents[2]
    script = (
        f"#!/bin/sh\ncd {shlex.quote(str(project))} || exit 1\n"
        f"exec {shlex.join(command)}\n"
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    created: list[Path] = []
    try:
        path = directory / "station.json"
        private_file(path, json.dumps(asdict(station), indent=2) + "\n")
        created.append(path)
        if rover is not None:
            path = directory / "users.json"
            private_file(path, json.dumps(rover, indent=2) + "\n")
            created.append(path)
        if publisher is not None:
            path = directory / "source-users.json"
            private_file(path, json.dumps(publisher, indent=2) + "\n")
            created.append(path)
        path = directory / "start.sh"
        private_file(path, script, 0o700)
        created.append(path)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        with suppress(OSError):
            directory.rmdir()
        raise
    print(f"Created {directory}")
    print(f"Start the station: {shlex.quote(str(directory / 'start.sh'))}")
    print(f"Mountpoint: {mountpoint}; listen address: {bind}:{listen_port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
