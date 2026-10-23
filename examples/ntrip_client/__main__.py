"""Feed NTRIP corrections to a UM982 and show the resulting position."""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Sequence
from contextlib import closing
from time import monotonic, sleep
from urllib.parse import urlsplit

from examples.ntrip_client import CorrectionStats, forward_corrections, gga_from_fix
from examples.ntrip_client.precision import PrecisionMonitor, precision_line
from examples.position_tracking import TrackPoint, collect_positions
from um982py import NtripClient, Receiver
from um982py.antenna import antenna_log
from um982py.commands import Log, modes
from um982py.console import ExampleParser, debug_header, run
from um982py.corrections import stale_correction
from um982py.errors import CommandRejected, ProtocolError, ResponseTimeout
from um982py.geodesy import ecef_from_geodetic
from um982py.ntrip import NtripError, ReconnectPolicy, retryable_ntrip_error
from um982py.protocol import StreamDecoder


class CasterDisconnected(ConnectionError):
    """The caster connection ended or could not be used."""


def _parser() -> ExampleParser:
    parser = ExampleParser(prog="python -m examples.ntrip_client", description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--caster", default="https://crtk.net:443/NEAR4")
    parser.add_argument("--ntrip-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--username")
    parser.add_argument("--password-env", default="NTRIP_PASSWORD")
    parser.add_argument(
        "--antenna", choices=("primary", "secondary"), default="primary"
    )
    parser.add_argument("--baseline-seconds", type=float, default=15.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--reconnect-delay", type=float, default=1.0)
    parser.add_argument("--reconnect-max-delay", type=float, default=30.0)
    parser.add_argument("--no-gga", action="store_true")
    parser.add_argument(
        "--reference-check",
        action="store_true",
        help="compare RTCM station coordinates with receiver BASEINFO",
    )
    parser.add_argument("--debug", action="store_true")
    return parser


def _password(args: argparse.Namespace) -> str | None:
    if not args.username:
        return None
    password = os.environ.get(args.password_env)
    if password is None and urlsplit(args.caster).hostname == "rtk2go.com":
        return "none"
    if password is None:
        raise ValueError(f"Set {args.password_env} for the NTRIP password")
    return password


def _sample(
    receiver: Receiver,
    log: Log,
    points: list[TrackPoint],
    *,
    antenna: str,
    timeout: float,
    debug: bool,
) -> bool:
    selected = antenna_log(log, antenna)
    try:
        record = receiver.execute(selected.read(binary=True), timeout=timeout)
        track, _ = collect_positions(
            (record,),
            status_field="sol_status" if log in (Log.SPPNAV, Log.ADRNAV) else None,
        )
    except CommandRejected as error:
        if debug:
            print(f"{log.value}: {error}", file=sys.stderr, flush=True)
        return False
    except (ResponseTimeout, ProtocolError, KeyError, ValueError):
        return True
    finally:
        receiver.drain_pending()
    if (
        log == Log.ADRNAV
        and track.points
        and stale_correction(
            track.points[0].position_type, track.points[0].correction_age_s
        )
    ):
        return True
    if track.points and (
        not points or track.points[0].timestamp > points[-1].timestamp
    ):
        points.append(track.points[0])
    return True


def _gga(receiver: Receiver, *, antenna: int) -> bytes | None:
    try:
        fix = receiver.fix(antenna=antenna)
    except ResponseTimeout:
        return None
    finally:
        receiver.drain_pending()
    return gga_from_fix(fix) if fix.valid else None


def _brief(
    point: TrackPoint | None, *, name: str, reference_epoch: float | None = None
) -> str:
    if point is None:
        return f"{name} waiting"
    sigma = point.horizontal_sigma_m
    accuracy = f"{sigma:.3f} m" if sigma is not None else "sigma unknown"
    line = f"{name} {point.position_type} {accuracy}"
    if reference_epoch is not None and reference_epoch - point.timestamp > 8:
        line += f" (stale {reference_epoch - point.timestamp:.0f} s)"
    return line


def _reference_check(
    receiver: Receiver, stats: CorrectionStats, timeout: float
) -> bool:
    """Compare a recently received RTCM station with a receiver snapshot."""
    now = monotonic()
    station = stats.station
    if (
        station is None
        or stats.station_received_at is None
        or now - stats.station_received_at > 20
    ):
        stats.reference_difference_m = None
        stats.reference_queried_at = None
        return True
    try:
        record = receiver.execute(Log.BASEINFO.read(binary=True), timeout=timeout)
        if record.integer("status") != 0:
            raise ValueError("receiver reports an invalid base station")
        coordinates = tuple(record.real(name) for name in ("x", "y", "z"))
        expected = ecef_from_geodetic(
            station.latitude, station.longitude, station.height_m
        )
        if (
            not all(math.isfinite(value) for value in coordinates)
            or math.hypot(*coordinates) < 1
        ):
            raise ValueError("receiver reference coordinates unavailable")
        stats.reference_difference_m = math.dist(coordinates, expected)
        stats.reference_queried_at = monotonic()
    except CommandRejected:
        stats.reference_difference_m = None
        stats.reference_queried_at = None
        return False
    except (ResponseTimeout, ProtocolError, KeyError, TypeError, ValueError):
        stats.reference_difference_m = None
        stats.reference_queried_at = None
    finally:
        receiver.drain_pending()
    return True


def _report(stats: CorrectionStats, monitor: PrecisionMonitor, *, debug: bool) -> None:
    selected = monitor.position()
    latest_code = monitor.corrected[-1] if monitor.corrected else None
    epoch = latest_code.timestamp if latest_code else None
    parts = [f"NTRIP: {stats.frames_forwarded} RTCM frames"]
    if stats.reference_enabled:
        if (
            stats.reference_queried_at is not None
            and stats.station_received_at is not None
            and stats.reference_difference_m is not None
            and monotonic() - stats.reference_queried_at <= 20
            and monotonic() - stats.station_received_at <= 20
        ):
            parts.append(
                f"reference coordinate difference {stats.reference_difference_m:.3f} m"
            )
        else:
            parts.append("reference comparison unavailable")
    if stats.connection_failures:
        parts.append(f"reconnects {stats.connection_failures}")
    parts.append(_brief(latest_code, name="SPPNAV"))
    parts.append(
        _brief(
            monitor.rtk[-1] if monitor.rtk else None,
            name="ADRNAV",
            reference_epoch=epoch,
        )
    )
    parts.append(f"selected {selected.source if selected else 'none'}")
    print("; ".join(parts), file=sys.stderr, flush=True)
    if not debug or selected is None:
        return
    detail = (
        f"Position: {selected.latitude:.9f}, {selected.longitude:.9f}, "
        f"{selected.altitude:.3f} m ellipsoidal; "
        f"{selected.solution_satellites}/{selected.satellites} satellites used/tracked"
    )
    if selected.correction_age_s is not None:
        detail += f"; correction age {selected.correction_age_s:.1f} s"
    if stats.station is not None:
        distance = stats.station.distance_km(selected.latitude, selected.longitude)
        detail += f"; base {stats.station.station_id} {distance:.1f} km away"
    print(detail, file=sys.stderr, flush=True)
    print(f"RTCM types: {dict(sorted(stats.message_types.items()))}", file=sys.stderr)


def _baseline(
    receiver: Receiver, args: argparse.Namespace, monitor: PrecisionMonitor
) -> None:
    if args.baseline_seconds == 0:
        return
    print(
        f"NTRIP: collecting baseline for {args.baseline_seconds:g} s", file=sys.stderr
    )
    deadline = monotonic() + args.baseline_seconds
    while monotonic() < deadline:
        _sample(
            receiver,
            Log.SPPNAV,
            monitor.baseline,
            antenna=args.antenna,
            timeout=min(args.timeout, 1.0),
            debug=args.debug,
        )
        sleep(min(2.0, max(0.0, deadline - monotonic())))


def _stream(
    receiver: Receiver,
    args: argparse.Namespace,
    stats: CorrectionStats,
    monitor: PrecisionMonitor,
    password: str | None,
) -> None:
    deadline = monotonic() + args.duration
    policy = ReconnectPolicy(args.reconnect_delay, args.reconnect_max_delay)
    delay = policy.initial_seconds
    while monotonic() < deadline:
        try:
            prior_frames = stats.frames_forwarded
            _stream_once(receiver, args, stats, monitor, password, deadline)
            return
        except (CasterDisconnected, NtripError) as error:
            stats.station_received_at = None
            stats.reference_queried_at = None
            stats.reference_difference_m = None
            cause = error.__cause__ if isinstance(error, CasterDisconnected) else error
            if cause is not None and not retryable_ntrip_error(cause):
                raise
            remaining = deadline - monotonic()
            if remaining <= 0:
                return
            if stats.frames_forwarded > prior_frames:
                delay = policy.initial_seconds
            wait = min(delay, remaining)
            stats.connection_failures += 1
            stats.retry_wait_seconds += wait
            print(
                f"NTRIP: connection lost ({error}); retrying in {wait:g}s",
                file=sys.stderr,
                flush=True,
            )
            sleep(wait)
            delay = policy.next_delay(delay)


def _stream_once(
    receiver: Receiver,
    args: argparse.Namespace,
    stats: CorrectionStats,
    monitor: PrecisionMonitor,
    password: str | None,
    deadline: float,
) -> None:
    antenna = 1 if args.antenna == "primary" else 2
    decoder = StreamDecoder()
    initial_gga = None if args.no_gga else _gga(receiver, antenna=antenna)
    caster = NtripClient(
        args.caster,
        username=args.username,
        password=password,
        initial_gga=initial_gga,
        timeout=args.timeout,
        version=args.ntrip_version,
    )
    try:
        caster.connect()
    except OSError as error:
        raise CasterDisconnected(str(error)) from error
    with closing(caster):
        caster.set_read_timeout(min(args.timeout, 1.0))
        address = f"{caster.host}:{caster.port}{caster.mountpoint}"
        print(
            f"NTRIP: connected to {address}",
            file=sys.stderr,
            flush=True,
        )
        if args.debug:
            print(
                "NTRIP: GGA disabled"
                if args.no_gga
                else "NTRIP: initial GGA sent"
                if initial_gga is not None
                else "NTRIP: waiting for a valid rover GGA",
                file=sys.stderr,
                flush=True,
            )
        now = monotonic()
        due = {
            "gga": now + 10,
            "spp": now,
            "rtk": now,
            "status": now + 5,
            "reference": now,
        }
        supported = {"spp": True, "rtk": True}
        reference_supported = True
        last_frame = now
        warned = False
        while monotonic() < deadline:
            try:
                data = caster.read()
            except TimeoutError:
                data = None
            except OSError as error:
                raise CasterDisconnected(str(error)) from error
            if data == b"":
                raise CasterDisconnected("caster closed the correction stream")
            if data and forward_corrections(
                receiver, data, decoder=decoder, stats=stats
            ):
                last_frame = monotonic()
                warned = False
            now = monotonic()
            if not args.no_gga and now >= due["gga"]:
                sentence = _gga(receiver, antenna=antenna)
                if sentence is not None:
                    try:
                        caster.send_gga(sentence)
                    except OSError as error:
                        raise CasterDisconnected(str(error)) from error
                    if args.debug:
                        print("NTRIP: GGA updated", file=sys.stderr, flush=True)
                due["gga"] = monotonic() + 10
            for key, log, interval, timeout, points in (
                ("spp", Log.SPPNAV, 2.0, 0.5, monitor.corrected),
                ("rtk", Log.ADRNAV, 5.0, 0.75, monitor.rtk),
            ):
                if stats.frames_forwarded and supported[key] and now >= due[key]:
                    supported[key] = _sample(
                        receiver,
                        log,
                        points,
                        antenna=args.antenna,
                        timeout=min(args.timeout, timeout),
                        debug=args.debug,
                    )
                    due[key] = monotonic() + interval
            if args.reference_check and reference_supported and now >= due["reference"]:
                reference_supported = _reference_check(
                    receiver, stats, min(args.timeout, 1.0)
                )
                due["reference"] = monotonic() + 10
            if monotonic() >= due["status"]:
                _report(stats, monitor, debug=args.debug)
                due["status"] = monotonic() + 5
            if args.debug and not warned and monotonic() - last_frame >= 15:
                print("NTRIP: no recent RTCM frames", file=sys.stderr, flush=True)
                warned = True
            if monotonic() - last_frame >= 60:
                raise CasterDisconnected("no RTCM corrections for 60 s")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    debug_header(args, "ntrip_client")
    if not math.isfinite(args.baseline_seconds) or args.baseline_seconds < 0:
        parser.error("--baseline-seconds must be finite and nonnegative")
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration must be finite and positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    try:
        ReconnectPolicy(args.reconnect_delay, args.reconnect_max_delay)
    except ValueError as error:
        parser.error(str(error))
    if args.username and args.username.lower().endswith("@example.com"):
        parser.error("replace the example.com address with your own NTRIP username")
    password = _password(args)
    stats = CorrectionStats()
    stats.reference_enabled = args.reference_check
    monitor = PrecisionMonitor()
    with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
        receiver.execute(modes.rover())
        print("NTRIP: receiver set to rover mode", file=sys.stderr)
        try:
            _baseline(receiver, args, monitor)
            _stream(receiver, args, stats, monitor, password)
        finally:
            _report(stats, monitor, debug=args.debug)
            print(precision_line(monitor), file=sys.stderr)
            fixed = {"L1_INT", "WIDE_INT", "NARROW_INT", "INS_RTKFIXED"}
            result = (
                "RTK: fixed solution observed"
                if any(point.position_type in fixed for point in monitor.rtk)
                else "RTK: no fixed solution observed"
            )
            print(result, file=sys.stderr)
    return 0 if stats.frames_forwarded else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
