"""Deliver modem-pushed PPPNAV fixes to a callback as they are read."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic

from examples.has_b2b_ppp_fix import (
    MeanFix,
    PppEpoch,
    PrecisionStatistics,
    format_position,
    format_precision,
    mean_fix,
    position_label,
    ppp_epochs,
    precision_statistics,
)
from um982py import Receiver
from um982py.capture import decode_records, load_records, open_receiver
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_debug_argument,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import ResponseTimeout
from um982py.subscriptions import temporary_subscriptions

__all__ = ["CyclicFix", "cycle_fixes", "main", "stream_fixes"]


@dataclass(frozen=True, slots=True)
class CyclicFix:
    """One delivered fix with its running mean and precision."""

    index: int
    epoch: PppEpoch
    running: MeanFix
    precision: PrecisionStatistics


def cycle_fixes(
    epochs: Sequence[PppEpoch],
    on_fix: Callable[[CyclicFix], bool | None],
    *,
    ppp_only: bool = True,
) -> int:
    """Deliver each fix with running statistics to the callback.

    The callback returns True to stop early. Returns delivered fixes.
    """
    selected = (
        tuple(item for item in epochs if item.is_ppp) if ppp_only else tuple(epochs)
    )
    history: list[PppEpoch] = []
    for item in selected:
        history.append(item)
        delivered = len(history)
        fix = CyclicFix(
            delivered,
            item,
            mean_fix(history, ppp_only=False),
            precision_statistics(history),
        )
        if on_fix(fix):
            break
    return len(history)


def stream_fixes(
    receiver: Receiver,
    on_fix: Callable[[CyclicFix], bool | None],
    *,
    cycles: int,
    cycle_seconds: float,
    timeout: float,
    ppp_only: bool = True,
    debug: bool = False,
) -> int:
    """Subscribe to PPPNAV once and deliver pushed fixes to the callback."""
    if cycles <= 0:
        raise ValueError("cycles must be positive")
    if cycle_seconds <= 0:
        raise ValueError("cycle seconds must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    planned = (
        Log.PPPNAV.wire_name(binary=True),
        Log.PPPNAV.output(cycle_seconds, binary=True),
    )
    seen: set[float] = set()
    history: list[PppEpoch] = []
    delivered = 0
    with temporary_subscriptions(receiver, planned):
        while delivered < cycles:
            try:
                message = receiver.receive(timeout=timeout)
            except ResponseTimeout:
                continue
            try:
                parsed = ppp_epochs(decode_records((message,), Log.PPPNAV))
            except (KeyError, TypeError, ValueError) as error:
                if debug:
                    print(f"cyclic debug: PPPNAV skipped: {error}", file=sys.stderr)
                continue
            for item in parsed:
                if item.epoch in seen:
                    continue
                seen.add(item.epoch)
                if ppp_only and not item.is_ppp:
                    continue
                history.append(item)
                delivered = len(history)
                fix = CyclicFix(
                    delivered,
                    item,
                    mean_fix(history, ppp_only=False),
                    precision_statistics(history),
                )
                if on_fix(fix):
                    return delivered
                if delivered >= cycles:
                    break
    return delivered


def _fix_line(fix: CyclicFix) -> str:
    """Beautified one-line fix with its running precision."""
    epoch = fix.epoch
    sigma = epoch.horizontal_sigma
    sigma_text = f"{sigma:.3f} m" if sigma is not None else "unknown"
    run = fix.precision.horizontal_scatter
    return (
        f"[{fix.index:>4}] {position_label(epoch.position_type):<14}"
        f"lat {epoch.latitude:.9f} lon {epoch.longitude:.9f} "
        f"h {epoch.height:.3f} m sigH {sigma_text} sats {epoch.satellites:>3} "
        f"| run n={fix.precision.epochs} scatterH {run:.3f} m"
    )


def _summary(collected: Sequence[CyclicFix], *, service: str) -> str:
    """Beautified running-mean position with precision statistics."""
    last = collected[-1]
    lines = [
        f" cyclic fixes: {len(collected)} delivered, service {service}",
        "-- RUNNING MEAN --",
        *format_position(last.running),
        "-- PRECISION --",
        *format_precision(last.precision),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Watch PPPNAV fixes cyclically and report each through a callback."""
    parser = ExampleParser(prog="python -m examples.has_b2b_ppp_fix.cyclic")
    add_receiver_arguments(parser)
    parser.add_argument(
        "--ppp-service",
        dest="ppp_service",
        choices=("AUTO", "E6-HAS", "B2B-PPP"),
        default="AUTO",
        help="free satellite PPP provider asserted on the receiver",
    )
    parser.add_argument(
        "--cycles", type=int, default=60, help="fixes to deliver before stopping"
    )
    parser.add_argument(
        "--cycle-seconds",
        type=float,
        default=5.0,
        help="PPPNAV subscription interval in seconds",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=300.0,
        help="live watch limit in seconds",
    )
    parser.add_argument(
        "--any-class",
        action="store_true",
        help="deliver non-PPP fixes as well",
    )
    parser.add_argument("--csv", type=Path, default=None, help="write delivered fixes")
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "has_b2b_ppp_fix.cyclic")
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    if args.cycle_seconds <= 0:
        parser.error("--cycle-seconds must be positive")
    collected: list[CyclicFix] = []
    stop_after: float | None = None
    if args.replay is None:
        stop_after = monotonic() + args.duration

    def on_fix(fix: CyclicFix) -> bool:
        collected.append(fix)
        print(_fix_line(fix), file=sys.stderr, flush=True)
        return stop_after is not None and monotonic() >= stop_after

    if args.replay is not None:
        delivered = cycle_fixes(
            ppp_epochs(load_records(args.replay, Log.PPPNAV)),
            on_fix,
            ppp_only=not args.any_class,
        )
    else:
        receiver = open_receiver(args)
        try:
            delivered = stream_fixes(
                receiver,
                on_fix,
                cycles=args.cycles,
                cycle_seconds=args.cycle_seconds,
                timeout=args.timeout,
                ppp_only=not args.any_class,
                debug=args.debug,
            )
        finally:
            receiver.close()
    if not collected:
        parser.error("no PPPNAV fixes delivered; check sky view or use --any-class")
    print(_summary(collected, service=args.ppp_service), file=sys.stderr)
    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            "fix,epoch_gps,lat_deg,lon_deg,hgt_m,pos_type,sats,"
            "run_lat_deg,run_lon_deg,run_hgt_m,run_scatter_h_m"
        ]
        rows.extend(
            f"{fix.index},{fix.epoch.epoch:.3f},"
            f"{fix.epoch.latitude:.9f},{fix.epoch.longitude:.9f},"
            f"{fix.epoch.height:.3f},{fix.epoch.position_type},"
            f"{fix.epoch.satellites},"
            f"{fix.running.latitude:.9f},{fix.running.longitude:.9f},"
            f"{fix.running.height:.3f},{fix.precision.horizontal_scatter:.4f}"
            for fix in collected
        )
        args.csv.write_text("\n".join(rows) + "\n", encoding="ascii")
    last = collected[-1]
    write_json(
        {
            "status": "ok",
            "service": args.ppp_service,
            "delivered": delivered,
            "fixes": [
                {
                    "index": fix.index,
                    "epoch": fix.epoch.epoch,
                    "latitude": fix.epoch.latitude,
                    "longitude": fix.epoch.longitude,
                    "height": fix.epoch.height,
                    "position_type": position_label(fix.epoch.position_type),
                    "satellites": fix.epoch.satellites,
                    "horizontal_sigma": fix.epoch.horizontal_sigma,
                    "height_sigma": fix.epoch.height_sigma,
                }
                for fix in collected
            ],
            "running_mean": {
                "latitude": last.running.latitude,
                "longitude": last.running.longitude,
                "height": last.running.height,
                "ecef": list(last.running.ecef),
                "epochs": last.running.epochs,
                "source": last.running.source,
            },
            "precision": asdict(last.precision),
        },
        args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
