# Show live GGA fixes with Doppler motion and receiver uncertainty in a dashboard.

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass, field
from shutil import get_terminal_size
from threading import Event, Lock, Thread
from time import monotonic
from urllib.parse import urlsplit

from examples._console import add_reliability_arguments, apply_reliability
from um982py import Receiver
from um982py.adapters import geojson_feature
from um982py.commands import Log, logging
from um982py.errors import CommandRejected, ProtocolError, ResponseTimeout
from um982py.live import PositionSession, PositionUpdate
from um982py.live_quality import LiveAssessment, LiveLimits, PositionMonitor
from um982py.messages import DopplerVelocity, Fix, Gsa, Message
from um982py.messages.enums import PositionType
from um982py.messages.navigation import BestNavigation
from um982py.rtk_session import RtkHealth

DEFAULT_NTRIP_URL = "http://rtk2go.com:2101/Weinstadt"
RTK2GO_PASSWORD = "none"  # noqa: S105 - documented public caster password
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalise_ntrip_url(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    candidate = url.strip()
    return candidate if "://" in candidate else f"http://{candidate}"


CORRECTION_LABELS = {
    "unknown": "unknown",
    "auto": "AUTO PPP",
    "e6-has": "E6-HAS",
    "b2b-ppp": "B2b-PPP",
    "l6-madoca": "L6 MADOCA",
}
DOPPLER_MAX_AGE_S = 2.0
REFRESH_S = 0.5
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
CYAN = "\x1b[36m"


@dataclass(frozen=True, slots=True)
class TimedDoppler:
    """A library Doppler solution with the example's host arrival time."""

    sample: DopplerVelocity
    received_monotonic: float


ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _visible(text: str) -> str:
    return ANSI_PATTERN.sub("", text)


def _fit(text: str, limit: int) -> str:
    if len(_visible(text)) <= limit:
        return text
    output: list[str] = []
    count = 0
    index = 0
    while index < len(text) and count < limit:
        match = ANSI_PATTERN.match(text, index)
        if match is not None:
            output.append(match.group())
            index = match.end()
            continue
        output.append(text[index])
        count += 1
        index += 1
    return "".join(output) + RESET


class DopplerMonitor:
    """Collect the newest Doppler report without blocking the receiver reader."""

    def __init__(self) -> None:
        self._latest: TimedDoppler | None = None
        self._lock = Lock()

    def accept(self, message: Message) -> None:
        try:
            sample = DopplerVelocity.from_message(message)
        except ProtocolError, TypeError, ValueError, KeyError:
            return
        with self._lock:
            self._latest = TimedDoppler(sample, monotonic())

    def latest(self) -> TimedDoppler | None:
        with self._lock:
            return self._latest


class NavigationMonitor:
    """Collect the newest BESTNAV solution for detailed fix type and precision."""

    def __init__(self) -> None:
        self._latest: BestNavigation | None = None
        self._lock = Lock()

    def accept(self, message: Message) -> None:
        try:
            navigation = BestNavigation.from_message(message)
        except ProtocolError, ValueError, TypeError, KeyError:
            return
        with self._lock:
            self._latest = navigation

    def latest(self) -> BestNavigation | None:
        with self._lock:
            return self._latest


class GsaMonitor:
    """Collect the newest GSA DOP report."""

    def __init__(self) -> None:
        self._latest: Gsa | None = None
        self._lock = Lock()

    def accept(self, message: Message) -> None:
        try:
            info = Gsa.from_message(message)
        except ProtocolError, TypeError, ValueError, KeyError:
            return
        with self._lock:
            self._latest = info

    def latest(self) -> Gsa | None:
        with self._lock:
            return self._latest


class MessageRouter:
    """Fan a stream frame out to the independent display monitors."""

    def __init__(
        self, doppler: DopplerMonitor, navigation: NavigationMonitor, gsa: GsaMonitor
    ) -> None:
        self.doppler = doppler
        self.navigation = navigation
        self.gsa = gsa

    def accept(self, message: Message) -> None:
        self.doppler.accept(message)
        self.navigation.accept(message)
        self.gsa.accept(message)


def _correction_label(
    declared: str, navigation: BestNavigation | None, fix: Fix
) -> str:
    ppp = (
        isinstance(navigation.position_type, PositionType)
        and navigation.position_type.is_ppp
        if navigation is not None
        else False
    )
    if declared != "unknown":
        label = CORRECTION_LABELS[declared]
        used = ppp or fix.quality in (2, 4, 5) or bool(fix.station_id)
        return f"{label} declared" if used else f"{label} declared, unused"
    if ppp:
        return "PPP, service unknown"
    if fix.quality in (4, 5) and fix.station_id:
        return f"RTCM base {fix.station_id}"
    if fix.quality == 2 and fix.station_id:
        return f"DGPS {fix.station_id}"
    return fix.quality_label


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None or not math.isfinite(value):
        return "---"
    return f"{value:.{digits}f}{suffix}"


def _precision(value: float | None) -> str:
    """Format a deviation in the smallest readable unit."""
    if value is None or not math.isfinite(value):
        return "---"
    magnitude = abs(value)
    if magnitude < 0.01:
        return f"{value * 1000:.1f} mm"
    if magnitude < 1:
        return f"{value * 100:.1f} cm"
    if magnitude < 10:
        return f"{value:.2f} m"
    return f"{value:.1f} m"


def _speed(value: float | None, *, compact: bool = False) -> str:
    """Format speed in m/s and km/h, or just km/h in narrow panels."""
    if value is None or not math.isfinite(value):
        return "---"
    kilometres = value * 3.6
    if compact:
        return f"{kilometres:.3f} km/h"
    return f"{value:.3f} m/s ({kilometres:.3f} km/h)"


def _coordinate(value: float | None, positive: str, negative: str) -> str:
    if value is None or not math.isfinite(value):
        return "---"
    return f"{abs(value):.7f}° {positive if value >= 0 else negative}"


def _bar(value: int | None, maximum: int, width: int = 10) -> str:
    if value is None or value < 0:
        return "?" * width
    filled = min(width, max(0, round(value * width / max(1, maximum))))
    return "█" * filled + "░" * (width - filled)


def _sparkline(values: Sequence[float], width: int = 10) -> str:
    if not values:
        return "·" * width
    selected = list(values[-width:])
    low, high = min(selected), max(selected)
    if high - low < 1e-9:
        return "▄" * len(selected)
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(
        blocks[min(7, int((value - low) / (high - low) * 7))] for value in selected
    )


def _signature(update: PositionUpdate) -> tuple[object, ...]:
    fix = update.fix
    return (
        fix.utc,
        fix.quality,
        fix.latitude,
        fix.longitude,
        fix.altitude_msl,
        fix.satellites,
        fix.hdop,
        fix.correction_age_s,
    )


@dataclass
class ScreenState:
    """Snapshot rendered by the dashboard or emitted as one plain line."""

    update: PositionUpdate | None = None
    assessment: LiveAssessment | None = None
    doppler: TimedDoppler | None = None
    navigation: BestNavigation | None = None
    gsa: Gsa | None = None
    corrections: RtkHealth | None = None
    correction_service: str = "unknown"
    rejected_logs: tuple[str, ...] = ()
    fixes: int = 0
    duplicates: int = 0
    speed_history: list[float] = field(default_factory=list)
    started_monotonic: float = field(default_factory=monotonic)


def _doppler_is_fresh(
    reading: TimedDoppler | None, update: PositionUpdate | None, now: float
) -> bool:
    if reading is None or update is None:
        return False
    arrival = update.received_monotonic
    return (
        abs(reading.received_monotonic - arrival) <= DOPPLER_MAX_AGE_S
        and now - reading.received_monotonic <= DOPPLER_MAX_AGE_S
    )


def _render(state: ScreenState) -> str:
    now = monotonic()
    width = max(76, min(get_terminal_size((96, 24)).columns, 116))
    inner = width - 2
    body_width = inner - 4
    compact = inner < 106

    def row(label: str, text: str, color: str = "") -> str:
        visible = _visible(f"{label:<9}{text}")[:body_width]
        body = _fit(text, max(0, body_width - 9))
        return (
            "│ "
            + BOLD
            + label.ljust(9)[:body_width]
            + RESET
            + (color or "")
            + body
            + RESET
            + " " * max(0, body_width - len(visible))
            + " │"
        )

    title = " UM982 LIVE NAVIGATION "
    lines = ["┌" + title + "─" * max(0, inner - len(title)) + "┐"]
    rejected = ", ".join(state.rejected_logs)
    if rejected:
        lines.append(row("WARN", f"optional logs rejected: {rejected}", YELLOW))
    update = state.update
    if update is None:
        lines.append(row("STATUS", "waiting for the first GGA fix", YELLOW))
        lines.append(row("INFO", "GPGGA is required, other logs are optional"))
        lines.append("└" + "─" * inner + "┘")
        lines.append(f"{DIM}Ctrl-C quit{RESET}")
        return "\n".join(lines) + "\n"

    fix = update.fix
    assessment = state.assessment
    reasons = assessment.reasons if assessment is not None else ()
    navigation = state.navigation
    gsa = state.gsa
    position_type = navigation.position_type_label if navigation else "---"
    converging = (
        isinstance(navigation.position_type, PositionType)
        and navigation.position_type is PositionType.PPP_CONVERGING
        if navigation is not None
        else False
    )
    status = (
        ", ".join(reasons) if reasons else ("converging" if converging else "healthy")
    )
    status_color = RED if reasons else (YELLOW if converging else GREEN)
    age = max(0.0, now - update.received_monotonic)
    correction = _correction_label(state.correction_service, navigation, fix)
    correction_age = _fmt(fix.correction_age_s, 1, " s")
    reading = state.doppler if _doppler_is_fresh(state.doppler, update, now) else None
    precision = None if navigation is None else navigation.precision
    std_text = (
        " ".join(
            (
                _precision(precision.east_std_m),
                _precision(precision.north_std_m),
                _precision(precision.up_std_m),
            )
        )
        if precision is not None
        else "unavailable"
    )
    hdop = _fmt(gsa.hdop if gsa is not None else fix.hdop, 2)
    pdop = _fmt(None if gsa is None else gsa.pdop, 2)
    vdop = _fmt(None if gsa is None else gsa.vdop, 2)

    if compact:
        lines.append(
            row(
                "FIX",
                f"{position_type:<18} {correction:<20} "
                f"{status_color}{status.upper()}{RESET}",
            )
        )
        lines.append(
            row(
                " ",
                f"GGA {fix.quality} {fix.quality_label:<12} "
                f"UTC {fix.utc or '---'} age {_fmt(age, 1, 's')} "
                f"corr {correction_age}",
                DIM,
            )
        )
        lines.append(
            row(
                "POSITION",
                f"{_coordinate(fix.latitude, 'N', 'S'):<17} "
                f"{_coordinate(fix.longitude, 'E', 'W')}",
            )
        )
        lines.append(
            row(
                " ",
                f"MSL {_fmt(fix.altitude_msl, 3, ' m'):<11} "
                f"ELL {_fmt(fix.ellipsoidal_height, 3, ' m'):<11} "
                f"std E/N/U {std_text}",
                DIM,
            )
        )
    else:
        lines.append(
            row(
                "FIX",
                f"{position_type:<18} GGA {fix.quality} "
                f"{fix.quality_label:<12} UTC {fix.utc or '---':>9}  "
                f"{status_color}{status.upper()}{RESET}",
            )
        )
        lines.append(
            row(
                " ",
                f"age {_fmt(age, 1, ' s'):<8} correction {correction:<20} "
                f"age {correction_age:<7} station {fix.station_id or '---'}",
                DIM,
            )
        )
        lines.append(
            row(
                "POSITION",
                f"{_coordinate(fix.latitude, 'N', 'S'):<17} "
                f"{_coordinate(fix.longitude, 'E', 'W'):<17} "
                f"MSL {_fmt(fix.altitude_msl, 3, ' m'):<12} "
                f"ELL {_fmt(fix.ellipsoidal_height, 3, ' m')}",
            )
        )
        lines.append(
            row(
                " ",
                f"std E/N/U {std_text:<25} HDOP {hdop:<6} PDOP {pdop:<6} VDOP {vdop}",
                DIM,
            )
        )

    if reading is None:
        lines.append(row("DOPPLER", "unavailable", YELLOW))
        lines.append(row(" ", "DOPPVELB has no recent computed fix", DIM))
    else:
        sample = reading.sample
        noise = 2.0 * (sample.ground_speed_std_mps or 0.0)
        significant = sample.ground_speed_mps >= max(noise, 0.02)
        course = _fmt(sample.course_true_deg, 1, "°") if significant else "---"
        quality = "" if significant else f" {YELLOW}noisy{RESET}"
        speed = f"{CYAN}{_speed(sample.ground_speed_mps, compact=compact):<30}{RESET}"
        motion = (
            f"speed {speed} course {course:<7} "
            f"up {_fmt(sample.vertical_speed_mps, 3, ' m/s'):<11}"
        )
        if not compact:
            motion += f" {_sparkline(state.speed_history)}"
        lines.append(row("DOPPLER", motion + quality))
        lines.append(
            row(
                " ",
                f"std {_precision(sample.ground_speed_std_mps)}/s "
                f"{_precision(sample.vertical_speed_std_mps)}/s  "
                f"latency {_fmt(sample.latency_s, 2, ' s')}  "
                f"age {_fmt(sample.age_s, 1, ' s')}",
                DIM,
            )
        )

    tracked = None if navigation is None else navigation.satellites_tracked
    used = navigation.satellites_used if navigation is not None else fix.satellites
    fix_mode = "---"
    if gsa is not None and gsa.fix_mode is not None:
        fix_mode = {1: "no fix", 2: "2D", 3: "3D"}.get(gsa.fix_mode, "---")
    if compact:
        lines.append(
            row(
                "GNSS",
                f"{used:>2}/{tracked if tracked is not None else '--':>2} sats  "
                f"HDOP {hdop}  PDOP {pdop}  VDOP {vdop}  "
                f"mode {'---' if gsa is None or gsa.mode is None else gsa.mode}",
            )
        )
    else:
        lines.append(
            row(
                "GNSS",
                f"{_bar(used, 20):<12} {used:>2}/"
                f"{'--' if tracked is None else tracked:>2} used/tracked  "
                f"GSA {fix_mode:<6} mode "
                f"{'---' if gsa is None or gsa.mode is None else gsa.mode}",
            )
        )
    uptime = max(0.0, now - state.started_monotonic)
    minutes, seconds = divmod(int(uptime), 60)
    lines.append(
        row(
            "STREAM",
            f"fixes {state.fixes:<5} duplicates {state.duplicates:<5} "
            f"connection {update.connection:<3} uptime "
            f"{minutes:02d}:{seconds:02d}",
        )
    )
    corrections = state.corrections
    if corrections is not None:
        relay_color = (
            GREEN
            if corrections.state == "connected"
            else RED
            if corrections.state == "failed"
            else YELLOW
        )
        detail = (
            f"{relay_color}{corrections.state.upper()}{RESET} "
            f"frames {corrections.frames_forwarded:<6} "
            f"age {_fmt(corrections.correction_age, 1, ' s'):<7} "
            f"reconnects {corrections.reconnects}"
        )
        if corrections.last_error:
            detail += f" {corrections.last_error}"
        lines.append(row("NTRIP", detail))
    lines.append("└" + "─" * inner + "┘")
    lines.append(f"{DIM}Ctrl-C quit · --plain for one line per fix{RESET}")
    return "\n".join(lines) + "\n"


def _format_plain(state: ScreenState) -> str:
    update = state.update
    if update is None:
        return "waiting for the first GGA fix"
    fix = update.fix
    reading = state.doppler
    assessment = state.assessment
    navigation = state.navigation
    precision = None if navigation is None else navigation.precision
    position_std = (
        None
        if precision is None
        else [precision.east_std_m, precision.north_std_m, precision.up_std_m]
    )
    sample = None if reading is None else reading.sample
    vertical_kmh = (
        None
        if sample is None or sample.vertical_speed_mps is None
        else sample.vertical_speed_mps * 3.6
    )
    return (
        f"{update.received_at.isoformat()} quality={fix.quality} "
        f"fix_type={fix.quality_label} ({fix.quality}) "
        f"position_type={navigation.position_type_label if navigation else '---'} "
        f"lat={fix.latitude} lon={fix.longitude} "
        f"height_msl={fix.altitude_msl} correction_age={fix.correction_age_s} "
        f"connection={update.connection} satellites={fix.satellites} hdop={fix.hdop} "
        f"pdop={None if state.gsa is None else state.gsa.pdop} "
        f"position_std_m={position_std} "
        f"speed_mps={None if sample is None else sample.ground_speed_mps} "
        f"speed_kmh={None if sample is None else sample.ground_speed_mps * 3.6} "
        f"speed_std_mps="
        f"{None if sample is None else sample.ground_speed_std_mps} "
        f"course_true_deg={None if sample is None else sample.course_true_deg} "
        f"vertical_speed_mps="
        f"{None if sample is None else sample.vertical_speed_mps} "
        f"vertical_speed_kmh={vertical_kmh} "
        f"vertical_speed_std_mps="
        f"{None if sample is None else sample.vertical_speed_std_mps} "
        f"ntrip_state={None if state.corrections is None else state.corrections.state} "
        f"ntrip_frames="
        f"{None if state.corrections is None else state.corrections.frames_forwarded} "
        f"reasons={() if assessment is None else assessment.reasons}"
    )


class Screen:
    """Render the newest state in place, or emit one plain line per fix."""

    def __init__(
        self,
        *,
        dashboard: bool,
        correction_service: str = "unknown",
        rejected_logs: list[str] | None = None,
    ) -> None:
        self.dashboard = dashboard
        self._rejected_logs = rejected_logs
        self._state = ScreenState(correction_service=correction_service)
        self._lock = Lock()
        if dashboard:
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()

    def note_rejected(self) -> None:
        with self._lock:
            self._state.rejected_logs = tuple(self._rejected_logs or ())

    def update(
        self,
        update: PositionUpdate,
        assessment: LiveAssessment,
        doppler: TimedDoppler | None,
        navigation: BestNavigation | None,
        gsa: Gsa | None,
        corrections: RtkHealth | None,
    ) -> None:
        with self._lock:
            self._state.update = update
            self._state.assessment = assessment
            self._state.doppler = doppler
            self._state.navigation = navigation
            self._state.gsa = gsa
            self._state.corrections = corrections
            self._state.fixes += 1
            if doppler is not None:
                self._state.speed_history.append(doppler.sample.ground_speed_mps)
                del self._state.speed_history[:-24]
        if self.dashboard:
            self.refresh()
        else:
            print(_format_plain(self._state), flush=True)

    def duplicate(self) -> None:
        with self._lock:
            self._state.duplicates += 1
        if self.dashboard:
            self.refresh()

    def refresh(self) -> None:
        if not self.dashboard:
            return
        with self._lock:
            text = _render(self._state)
            sys.stdout.write("\x1b[H\x1b[J" + text)
            sys.stdout.flush()

    def close(self) -> None:
        if self.dashboard:
            with self._lock:
                sys.stdout.write("\x1b[?25h\n")
                sys.stdout.flush()


def report_status(monitor: PositionMonitor, stop: Event) -> None:
    """Report changed position health even when the receiver stops sending."""
    previous: tuple[str, ...] | None = None
    while not stop.wait(0.5):
        reasons = monitor.status().reasons
        if reasons != previous:
            if reasons:
                print(
                    f"position health: {', '.join(reasons)}",
                    file=sys.stderr,
                    flush=True,
                )
            elif previous:
                print("position health: recovered", file=sys.stderr, flush=True)
            previous = reasons


def refresh_screen(screen: Screen, stop: Event) -> None:
    """Redraw the dashboard while waiting for the next fix."""
    while not stop.wait(REFRESH_S):
        screen.refresh()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="serial port or tcp://host:port")
    parser.add_argument("--baud", type=int, default=115200)
    rate = parser.add_mutually_exclusive_group()
    rate.add_argument("--interval", type=float, help="GGA output interval in seconds")
    rate.add_argument("--rate-hz", type=float, help="GGA output rate in Hz")
    parser.add_argument(
        "--geojson", action="store_true", help="output WGS84 fixes as GeoJSON lines"
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="write one line per fix without a dashboard",
    )
    parser.add_argument(
        "--no-doppler", action="store_true", help="do not request DOPPVEL velocity"
    )
    parser.add_argument(
        "--request-gsa",
        action="store_true",
        help="request GSA output; DOP is still read when the receiver sends it",
    )
    parser.add_argument(
        "--ntrip",
        action="store_true",
        help=f"relay {DEFAULT_NTRIP_URL}",
    )
    parser.add_argument(
        "--ntrip-url", help="explicit NTRIP mountpoint URL; implies --ntrip"
    )
    parser.add_argument(
        "--ntrip-username",
        help="rtk2go email login; defaults to NTRIP_USERNAME",
    )
    parser.add_argument(
        "--ntrip-password-env", default="NTRIP_PASSWORD", help="password variable"
    )
    parser.add_argument("--ntrip-version", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--correction-service",
        choices=tuple(CORRECTION_LABELS),
        default="unknown",
        help="declared PPP service label, shown without inferring the source",
    )
    parser.add_argument(
        "--max-gap", type=float, help="maximum arrival interval in seconds"
    )
    parser.add_argument(
        "--max-correction-age", type=float, help="maximum correction age in seconds"
    )
    add_reliability_arguments(parser)
    args = parser.parse_args(argv)
    ntrip_url = _normalise_ntrip_url(
        args.ntrip_url or (DEFAULT_NTRIP_URL if args.ntrip else None)
    )
    ntrip_username = args.ntrip_username or os.environ.get("NTRIP_USERNAME")
    ntrip_password = None
    if ntrip_url is not None:
        ntrip_password = os.environ.get(args.ntrip_password_env)
        if urlsplit(ntrip_url).hostname == "rtk2go.com":
            if ntrip_username is None or not EMAIL_PATTERN.match(ntrip_username):
                parser.error(
                    "rtk2go.com needs a well-formed email username; pass "
                    "--ntrip-username or set NTRIP_USERNAME"
                )
            ntrip_password = ntrip_password or RTK2GO_PASSWORD
        elif ntrip_username is not None and ntrip_password is None:
            parser.error(f"Set {args.ntrip_password_env} for the NTRIP password")
    try:
        interval = logging.output_interval(args.interval, args.rate_hz)
    except ValueError as error:
        parser.error(str(error))
    command_specs = [
        ("GPGGA", Log.GPGGA.output(interval)),
        ("BESTNAV", Log.BESTNAV.output(interval, binary=True)),
    ]
    if not args.no_doppler:
        command_specs.append(("DOPPVEL", Log.DOPPVEL.output(interval, binary=True)))
    if args.request_gsa:
        command_specs.append(("GSA", Log.GPGSA.output(interval)))

    doppler = DopplerMonitor()
    navigation = NavigationMonitor()
    gsa = GsaMonitor()
    monitor = PositionMonitor(
        LiveLimits(max_gap_s=args.max_gap, max_correction_age_s=args.max_correction_age)
    )
    stop = Event()
    rejected_logs: list[str] = []
    screen = Screen(
        dashboard=not args.geojson and not args.plain and sys.stdout.isatty(),
        correction_service=args.correction_service,
        rejected_logs=rejected_logs,
    )

    def configure(receiver: Receiver) -> None:
        apply_reliability(receiver, args)
        for name, command in command_specs:
            try:
                receiver.execute(command)
            except (CommandRejected, ResponseTimeout) as error:
                if name == "GPGGA":
                    raise
                response = getattr(error, "response", str(error))
                text = f"{name} ({response})"
                if text not in rejected_logs:
                    rejected_logs.append(text)
                    print(
                        f"optional log unavailable: {text}",
                        file=sys.stderr,
                        flush=True,
                    )
        screen.note_rejected()

    def receiver_factory() -> Receiver:
        return Receiver.connect(args.target, args.baud)

    router = MessageRouter(doppler, navigation, gsa)
    if ntrip_url is None:
        session = PositionSession(
            receiver_factory,
            configure=configure,
            on_message=router.accept,
            subscribe=True,
        )
    else:
        session = PositionSession(
            receiver_factory,
            configure=configure,
            on_message=router.accept,
            subscribe=True,
            ntrip_url=ntrip_url,
            ntrip_username=ntrip_username,
            ntrip_password=ntrip_password,
            ntrip_version=args.ntrip_version,
        )
    watchers = [
        Thread(target=report_status, args=(monitor, stop), daemon=True)
        if args.max_gap is not None or args.max_correction_age is not None
        else None,
        Thread(target=refresh_screen, args=(screen, stop), daemon=True)
        if screen.dashboard
        else None,
    ]
    for watcher in watchers:
        if watcher is not None:
            watcher.start()
    previous_signature: tuple[object, ...] | None = None
    try:
        with closing(session.positions(stop)) as positions:
            for update in positions:
                signature = _signature(update)
                if signature == previous_signature:
                    screen.duplicate()
                    continue
                previous_signature = signature
                assessment = monitor.observe(update)
                reading = doppler.latest()
                nav = navigation.latest()
                gsa_info = gsa.latest()
                if args.geojson:
                    feature = geojson_feature(update, reference_frame="WGS84")
                    if feature is not None:
                        properties = feature["properties"]
                        properties["fix_type"] = update.fix.quality_label
                        properties["position_type"] = (
                            nav.position_type_label if nav else "---"
                        )
                        properties["assessment_reasons"] = assessment.reasons
                        properties["doppler_speed_mps"] = (
                            None if reading is None else reading.sample.ground_speed_mps
                        )
                        properties["doppler_speed_kmh"] = (
                            None
                            if reading is None
                            else reading.sample.ground_speed_mps * 3.6
                        )
                        properties["doppler_speed_std_mps"] = (
                            None
                            if reading is None
                            else reading.sample.ground_speed_std_mps
                        )
                        health = session.correction_health()
                        properties["ntrip_state"] = (
                            None if health is None else health.state
                        )
                        print(json.dumps(feature, allow_nan=False), flush=True)
                    continue
                screen.update(
                    update,
                    assessment,
                    reading,
                    nav,
                    gsa_info,
                    session.correction_health(),
                )
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for watcher in watchers:
            if watcher is not None:
                watcher.join()
        screen.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
