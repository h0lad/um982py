"""Serves a reference station over NTRIP."""

import argparse
import asyncio
import getpass
import ipaddress
import logging
import os
import signal
import ssl
from contextlib import AsyncExitStack
from functools import partial
from pathlib import Path

from examples.ntrip_server.auth import Credentials, hash_password
from examples.ntrip_server.caster import Caster, Hub, Limits, listen
from examples.ntrip_server.source import (
    Upstream,
    read_receiver,
    read_upstream,
    supervise,
)
from examples.ntrip_server.station import Station
from examples.ntrip_server.status import StatusSettings, StatusSite, listen_status
from examples.ntrip_server.survey import capture_survey
from um982py.capture import read_frames
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.messages import RtcmMessage


def _build_parser() -> ExampleParser:
    parser = ExampleParser(prog="python -m examples.ntrip_server", description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument("--station", type=Path, help="reviewed ARP station JSON")
    parser.add_argument("--users", type=Path, help="0600 JSON username/scrypt mapping")
    parser.add_argument(
        "--mode",
        choices=("public", "private"),
        help="public permits guest rovers, while private requires named accounts",
    )
    parser.add_argument(
        "--source-users",
        type=Path,
        help="0600 JSON source credentials that enable incoming source upload mode",
    )
    parser.add_argument("--public", action="store_true", help="allow anonymous GET")
    parser.add_argument("--hash-password", action="store_true")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=2101)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--max-clients", type=int, default=1024)
    parser.add_argument("--max-per-ip", type=int, default=16)
    parser.add_argument("--max-per-user", type=int, default=32)
    parser.add_argument("--queue-frames", type=int, default=32)
    parser.add_argument("--upstream-host")
    parser.add_argument("--upstream-port", type=int, default=443)
    parser.add_argument("--upstream-user")
    parser.add_argument("--upstream-ca", type=Path)
    parser.add_argument("--status-port", type=int, help="enable the read-only website")
    parser.add_argument("--status-bind", default="127.0.0.1")
    parser.add_argument(
        "--status-caster-url", help="public caster origin, including port"
    )
    parser.add_argument("--status-contact-url", help="HTTPS page for access requests")
    parser.add_argument("--status-max-clients", type=int, default=64)
    parser.add_argument("--status-per-ip", type=int, default=8)
    parser.add_argument("--survey-output", type=Path)
    parser.add_argument("--seconds", type=float, default=86400)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--marker-name", default="UM982")
    parser.add_argument("--antenna-type", help="exact IGS antenna and radome code")
    parser.add_argument("--antenna-serial")
    parser.add_argument("--receiver-serial")
    parser.add_argument("--receiver-firmware")
    parser.add_argument(
        "--approx-position", type=float, nargs=3, metavar=("X", "Y", "Z")
    )
    parser.add_argument("--antenna-hen", type=float, nargs=3, metavar=("H", "E", "N"))
    parser.add_argument(
        "--debug",
        action="store_true",
        help="verbose server logging to stderr",
    )
    parser.add_argument("--l2c-code", choices=("2S", "2L", "2X"))
    return parser


def create_tls_context(args: argparse.Namespace) -> ssl.SSLContext | None:
    address = ipaddress.ip_address(args.bind)
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ValueError("--tls-cert and --tls-key must be supplied together")
    if args.tls_cert is None:
        if not address.is_loopback:
            raise ValueError("non-loopback listeners require a TLS certificate and key")
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_COMPRESSION
    context.load_cert_chain(args.tls_cert, args.tls_key)
    return context


async def serve(
    args: argparse.Namespace,
    station: Station,
    credentials: Credentials,
    context: ssl.SSLContext | None,
    *,
    status: StatusSettings | None = None,
) -> None:
    limits = Limits(
        connections=args.max_clients,
        per_ip=args.max_per_ip,
        per_user=args.max_per_user,
        queue_frames=args.queue_frames,
    )
    hub = Hub(station, limits)
    source_credentials = (
        Credentials.load(args.source_users) if args.source_users else None
    )
    caster = Caster(
        hub,
        credentials,
        public=args.public,
        source_credentials=source_credentials,
        protect_table=args.mode == "private",
    )
    website = StatusSite(caster, status) if status is not None else None
    if args.upstream_host:
        upstream_context = ssl.create_default_context(cafile=args.upstream_ca)
        upstream_context.minimum_version = ssl.TLSVersion.TLSv1_2
        upstream = Upstream(
            args.upstream_host,
            args.upstream_port,
            args.upstream_user,
            os.environ["NTRIP_UPSTREAM_PASSWORD"],
            upstream_context,
        )
        operation = partial(read_upstream, hub, upstream)
    elif not args.source_users:
        operation = partial(
            read_receiver, hub, args.port, args.baud, timeout=args.timeout
        )
    else:
        operation = None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stopped.set)
    try:
        async with AsyncExitStack() as stack:
            server = await listen(caster, args.bind, args.listen_port, context)
            await stack.enter_async_context(server)
            if website is not None:
                status_context = (
                    None
                    if ipaddress.ip_address(args.status_bind).is_loopback
                    else context
                )
                status_server = await listen_status(
                    website, args.status_bind, args.status_port, status_context
                )
                await stack.enter_async_context(status_server)
                logging.info(
                    "Status website ready on %s:%s", args.status_bind, args.status_port
                )
            async with asyncio.TaskGroup() as group:
                producer = (
                    group.create_task(supervise(hub, operation)) if operation else None
                )
                reporter = group.create_task(report_status(caster))
                updater = group.create_task(website.update()) if website else None
                logging.info(
                    "NTRIP listener ready on %s:%s", args.bind, args.listen_port
                )
                await stopped.wait()
                if producer is not None:
                    producer.cancel()
                reporter.cancel()
                if updater is not None:
                    updater.cancel()
    finally:
        if website is not None:
            await website.close()
        await caster.close()
        for name in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(name)


async def report_status(caster: Caster) -> None:
    while True:
        await asyncio.sleep(60)
        logging.info(
            "ready=%s connections=%d streams=%d frames=%d slow=%d rejected=%d",
            caster.hub.is_ready,
            len(caster.tasks),
            len(caster.hub.clients),
            caster.hub.frames,
            caster.hub.slow_clients,
            caster.rejected,
        )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.hash_password:
        print(hash_password(getpass.getpass("NTRIP password (16+ bytes): ")))
        return 0
    if args.mode == "public":
        args.public = True
    elif args.mode == "private" and args.public:
        parser.error("--mode private cannot be combined with --public")
    if args.antenna not in ("primary", "1"):
        parser.error("reference station and survey require ANT1/primary")
    if args.replay is not None and not args.replay.is_file():
        parser.error(f"replay file does not exist: {args.replay}")
    if args.survey_output is not None:
        if args.json is not None:
            parser.error("use --survey-output for the RINEX result, without --json")
        required = (
            "antenna_type",
            "antenna_serial",
            "receiver_serial",
            "receiver_firmware",
            "approx_position",
            "antenna_hen",
        )
        if any(getattr(args, name) is None for name in required):
            parser.error("survey requires antenna, receiver, ECEF and H/E/N metadata")
        if args.survey_output.exists():
            parser.error("--survey-output must name a new file")
        if args.interval <= 0 or args.seconds <= 0:
            parser.error("survey duration and cadence must be positive")
        capture_survey(args)
        return 0
    if args.station is None:
        parser.error("--station is required for broadcasting and RTCM replay checks")
    station = Station.load(args.station)
    if args.replay is not None:
        accepted = sum(
            station.validate_frame(message)
            for message in read_frames(args.replay)
            if isinstance(message, RtcmMessage)
        )
        if not accepted:
            parser.error("capture has no RTCM frames from the configured profile")
        print(f"Validated {accepted} RTCM frames; offline replay is not broadcast")
        if args.json is not None:
            write_json({"rtcm_frames": accepted, "broadcast": False}, args.json)
        return 0
    if args.record is not None or args.json is not None:
        parser.error("--record is for surveys; --json is for offline RTCM checks")
    if not args.public and args.users is None:
        parser.error("supply --users or explicitly enable --public")
    if args.source_users and args.upstream_host:
        parser.error("--source-users and --upstream-host select different source modes")
    for value in (args.listen_port, args.upstream_port):
        if not 1 <= value <= 65535:
            parser.error("TCP ports must be in 1..65535")
    if args.upstream_host and (
        not args.upstream_user or not os.environ.get("NTRIP_UPSTREAM_PASSWORD")
    ):
        parser.error("relay requires --upstream-user and NTRIP_UPSTREAM_PASSWORD")
    if args.upstream_host and any(c in args.upstream_host for c in "\r\n /\t"):
        parser.error("invalid upstream host")
    credentials = Credentials.load(args.users) if args.users else Credentials({})
    context = create_tls_context(args)
    status_settings = None
    if args.status_port is not None:
        if not 1 <= args.status_port <= 65535 or not args.status_caster_url:
            parser.error(
                "status website needs a valid --status-port and --status-caster-url"
            )
        if not ipaddress.ip_address(args.status_bind).is_loopback and context is None:
            parser.error(
                "non-loopback status listeners require TLS certificate and key"
            )
        if (
            args.mode == "private"
            and not ipaddress.ip_address(args.status_bind).is_loopback
        ):
            parser.error(
                "private mode requires the unauthenticated status site on loopback"
            )
        status_settings = StatusSettings(
            args.status_caster_url,
            args.status_contact_url,
            relay=bool(args.upstream_host),
            connections=args.status_max_clients,
            per_ip=args.status_per_ip,
        )
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    asyncio.run(serve(args, station, credentials, context, status=status_settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
