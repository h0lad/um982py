"""Create a reusable NTRIP rover startup script."""

import argparse
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit

from examples.ntrip_server.setup import ask, choice, integer
from um982py import NtripClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path("ntrip-rover"),
        help="new directory for the startup script (default: ntrip-rover)",
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        parser.error(f"directory already exists: {directory}; choose a new directory")
    print(
        "NTRIP rover setup: obtain the caster address and mountpoint from the provider."
    )
    print("Use https when the provider supports TLS; include the port and mountpoint.")
    print("Example only: http://rtk2go.com:2101/Weinstadt")
    while True:
        caster = ask("Caster URL (including /mountpoint)")
        try:
            NtripClient(caster)
        except ValueError as error:
            print(f"Invalid caster URL: {error}")
        else:
            break
    address = urlsplit(caster)
    is_rtk2go = address.hostname == "rtk2go.com"
    version = integer("NTRIP version", 1, 2, "1" if is_rtk2go else "2")
    print("Guest needs no login; password uses a provider account.")
    print("RTK2go uses your real email address and password 'none'.")
    access = choice(
        "Access", ("guest", "password", "rtk2go"), "rtk2go" if is_rtk2go else "guest"
    )
    if access == "rtk2go" and not is_rtk2go:
        parser.error("the rtk2go access option requires an rtk2go.com URL")
    username = None
    if access != "guest":
        while True:
            username = ask("RTK2go email" if access == "rtk2go" else "Caster username")
            if "\r" in username or "\n" in username or ":" in username:
                print("Username cannot contain a colon or line break.")
            elif username.lower().endswith("@example.com"):
                print("Enter your real account, not the example address.")
            elif access == "rtk2go" and "@" not in username:
                print("RTK2go requires a real email address.")
            else:
                break
    if address.scheme == "http":
        print("HTTP sends credentials and any rover position without encryption.")
    print("The UM982 must have an antenna with a clear view of the sky.")
    port = ask("Receiver serial port", "/dev/ttyUSB0")
    baud = integer("Receiver baud rate", 1, 4_000_000, "921600")
    duration = integer("Correction observation time in seconds", 1, 86400, "60")
    print("GGA sends the rover's approximate position to the caster every 10 seconds.")
    gga = choice("Send GGA when a valid fix is available", ("yes", "no"), "yes")
    command = [
        sys.executable,
        "-m",
        "examples.ntrip_client",
        "--port",
        port,
        "--baud",
        str(baud),
        "--caster",
        caster,
        "--ntrip-version",
        str(version),
        "--duration",
        str(duration),
        "--debug",
    ]
    if username is not None:
        command += ["--username", username]
    if gga == "no":
        command.append("--no-gga")
    prefix = ""
    if access == "password":
        prompt = (
            'import getpass,sys; sys.stdout.write(getpass.getpass("Caster password: "))'
        )
        read_password = shlex.join([sys.executable, "-c", prompt])
        prefix = (
            'if [ "${NTRIP_PASSWORD+x}" != x ]; then\n'
            f"  NTRIP_PASSWORD=$({read_password}) || exit 1\n"
            "  export NTRIP_PASSWORD\n"
            "fi\n"
        )
    elif access == "rtk2go":
        prefix = "NTRIP_PASSWORD=none\nexport NTRIP_PASSWORD\n"
    project = Path(__file__).resolve().parents[2]
    script = (
        f"#!/bin/sh\ncd {shlex.quote(str(project))} || exit 1\n"
        f"{prefix}exec {shlex.join(command)}\n"
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        descriptor = os.open(
            directory / "start.sh", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(script)
    except BaseException:
        (directory / "start.sh").unlink(missing_ok=True)
        directory.rmdir()
        raise
    print(f"Created {directory}")
    print(f"Start the rover: {shlex.quote(str(directory / 'start.sh'))}")
    print("No network connection was attempted during setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
