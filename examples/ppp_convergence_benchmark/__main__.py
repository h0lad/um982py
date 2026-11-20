# Benchmark PPP convergence against precision targets and an optional reference.

from __future__ import annotations

import argparse
import math
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples.ppp_convergence_benchmark import (
    PppEpoch,
    epoch_from_navigation,
    percentile,
)
from examples.time_transfer import leap_seconds
from um982py import Receiver
from um982py.assessment import PositionLimits
from um982py.commands import Log
from um982py.convergence import ConvergenceMonitor
from um982py.messages import Message
from um982py.messages.enums import PositionType
from um982py.messages.navigation import BestNavigation
from um982py.quality import FixClass, classify
from um982py.subscriptions import temporary_subscriptions


def _parse_ecef(text: str) -> tuple[float, float, float]:
    """Parse ``X,Y,Z`` reference coordinates in metres."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ValueError("expected three comma-separated metres")
    values = tuple(float(part) for part in parts)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("reference coordinates must be finite")
    return (values[0], values[1], values[2])


def _to_bestnav(message: Message) -> BestNavigation | None:
    """Decode a BESTNAV/PPPNAV message, or return None for other traffic."""
    from um982py.errors import ProtocolError

    try:
        return BestNavigation.from_message(message)
    except ProtocolError:
        return None


def _collect_epochs(
    args: argparse.Namespace,
) -> tuple[list[PppEpoch], float | None, float | None, dict[str, int]]:
    """Stream distinct, valid PPP epochs and track convergence."""
    limits = PositionLimits(
        max_horizontal_rms_m=args.horizontal_limit,
        max_vertical_std_m=args.vertical_limit,
        max_epoch_age_s=args.max_epoch_age,
        max_correction_age_s=None,
        allowed_fix_classes=frozenset({FixClass.PPP, FixClass.PPP_CONVERGING}),
    )

    def new_monitor() -> ConvergenceMonitor:
        return ConvergenceMonitor(
            limits,
            min_epochs=args.min_epochs,
            hold_seconds=args.hold_seconds,
            max_gap_seconds=args.max_gap,
            timeout=args.duration,
        )

    monitor = new_monitor()

    command = Log.BESTNAV.output(args.interval)
    epochs: list[PppEpoch] = []
    first_fix_elapsed: float | None = None
    convergence_elapsed_s: float | None = None
    started = time.monotonic()
    counts: Counter[str] = Counter()
    last_epoch: float | None = None

    with (
        Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver,
        temporary_subscriptions(receiver, (Log.BESTNAV.wire_name(), command)),
    ):
        while time.monotonic() - started < args.duration:
            from um982py.errors import ResponseTimeout

            try:
                message = receiver.receive(
                    timeout=min(
                        args.timeout,
                        max(0.001, args.duration - (time.monotonic() - started)),
                    )
                )
            except ResponseTimeout:
                continue
            nav = _to_bestnav(message)
            if nav is None:
                continue
            elapsed = time.monotonic() - started
            try:
                fix_class = (
                    classify(int(nav.position_type))
                    if not isinstance(nav.position_type, str)
                    else classify(int(PositionType[nav.position_type]))
                )
            except (ValueError, KeyError):
                monitor = new_monitor()
                counts["unknown_type"] += 1
                continue
            if not nav.valid or fix_class not in (
                FixClass.PPP,
                FixClass.PPP_CONVERGING,
            ):
                monitor = new_monitor()
                counts["non_ppp_or_invalid"] += 1
                continue
            stamp = nav.epoch_gps_seconds
            if stamp is None or not math.isfinite(stamp):
                monitor = new_monitor()
                counts["missing_epoch"] += 1
                continue
            if last_epoch is not None and stamp <= last_epoch:
                if stamp < last_epoch:
                    monitor = new_monitor()
                counts["duplicate_or_reversed"] += 1
                continue
            if last_epoch is not None and stamp - last_epoch > args.max_gap:
                counts["gaps"] += 1
            last_epoch = stamp
            counts["accepted"] += 1
            if first_fix_elapsed is None:
                first_fix_elapsed = elapsed
            status = None
            if args.trust_host_clock:
                now = datetime.now(UTC).replace(tzinfo=None)
                gps_seconds = (
                    now - datetime(1980, 1, 6)
                ).total_seconds() + leap_seconds(now)
                status = monitor.observe(nav, now_gps_seconds=gps_seconds)

            epoch = epoch_from_navigation(nav, elapsed, args.reference_ecef)
            epoch = PppEpoch(
                epoch=epoch.epoch,
                elapsed_s=epoch.elapsed_s,
                latitude=epoch.latitude,
                longitude=epoch.longitude,
                height_ellipsoidal=epoch.height_ellipsoidal,
                horizontal_rms_m=epoch.horizontal_rms_m,
                vertical_std_m=epoch.vertical_std_m,
                converged=status.converged if status is not None else False,
                east_error_m=epoch.east_error_m,
                north_error_m=epoch.north_error_m,
                up_error_m=epoch.up_error_m,
                horizontal_error_m=epoch.horizontal_error_m,
                three_d_error_m=epoch.three_d_error_m,
            )
            epochs.append(epoch)
            if (
                convergence_elapsed_s is None
                and status is not None
                and status.converged
            ):
                convergence_elapsed_s = elapsed
            if elapsed >= args.duration:
                break

    return epochs, first_fix_elapsed, convergence_elapsed_s, dict(counts)


def _payload(
    epochs: Sequence[PppEpoch],
    first_fix_s: float | None,
    convergence_s: float | None,
    horizontal_limit: float,
    vertical_limit: float,
) -> dict[str, object]:
    h_errors = [
        e.horizontal_error_m for e in epochs if e.horizontal_error_m is not None
    ]
    v_errors = [abs(e.up_error_m) for e in epochs if e.up_error_m is not None]
    reported_h = [e.horizontal_rms_m for e in epochs if e.horizontal_rms_m is not None]
    reported_v = [e.vertical_std_m for e in epochs if e.vertical_std_m is not None]

    def _cdf(values: Sequence[float]) -> dict[str, float | None]:
        return {
            "50th": percentile(values, 50.0),
            "68th": percentile(values, 68.0),
            "95th": percentile(values, 95.0),
        }

    return {
        "limits": {
            "horizontal_rms_m": horizontal_limit,
            "vertical_std_m": vertical_limit,
        },
        "summary": {
            "total_epochs": len(epochs),
            "converged_epochs": sum(1 for e in epochs if e.converged),
            "first_fix_s": first_fix_s,
            "convergence_s": convergence_s,
        },
        "errors": {
            "horizontal_error_cdf_m": _cdf(h_errors),
            "vertical_error_cdf_m": _cdf(v_errors),
        },
        "reported_precision": {
            "horizontal_rms_cdf_m": _cdf(reported_h),
            "vertical_std_cdf_m": _cdf(reported_v),
        },
        "epochs": [
            {
                "elapsed_s": round(e.elapsed_s, 3),
                "latitude": e.latitude,
                "longitude": e.longitude,
                "height_ellipsoidal": e.height_ellipsoidal,
                "horizontal_rms_m": e.horizontal_rms_m,
                "vertical_std_m": e.vertical_std_m,
                "converged": e.converged,
                "horizontal_error_m": e.horizontal_error_m,
                "three_d_error_m": e.three_d_error_m,
            }
            for e in epochs
        ],
        "limitation": (
            "Convergence is defined against receiver-reported precision, not an "
            "independent truth.  When a reference ECEF position is supplied, the "
            "reported errors are relative to that reference and include datum, "
            "antenna and multipath biases."
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.ppp_convergence_benchmark",
        description=(
            "Benchmark PPP convergence: time-to-first-fix, sustained "
            "precision window, and optional reference error CDF."
        ),
    )
    add_receiver_arguments(parser, replay=False)
    parser.add_argument(
        "--duration",
        type=float,
        default=600.0,
        help="benchmark duration in seconds",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="BESTNAV output interval in seconds",
    )
    parser.add_argument(
        "--horizontal-limit",
        type=float,
        default=0.20,
        help="sustained horizontal RMS limit in metres",
    )
    parser.add_argument(
        "--vertical-limit",
        type=float,
        default=0.40,
        help="sustained vertical std limit in metres",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=30.0,
        help="duration the position must stay within limits",
    )
    parser.add_argument(
        "--min-epochs",
        type=int,
        default=5,
        help="minimum accepted epochs in the hold window",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=5.0,
        help="maximum allowed gap between epochs in seconds",
    )
    parser.add_argument(
        "--max-epoch-age",
        type=float,
        default=2.0,
        help="maximum acceptable receiver epoch age in seconds",
    )
    parser.add_argument(
        "--trust-host-clock",
        action="store_true",
        help="assume host UTC is accurate for receiver epoch freshness",
    )
    parser.add_argument(
        "--reference-ecef",
        type=_parse_ecef,
        help="optional reference ECEF position as X,Y,Z in metres",
    )
    parser.add_argument(
        "--service",
        choices=("E6-HAS", "B2B-PPP", "AUTO"),
        help="PPP service to enable; omit to use the current receiver solution",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.service is not None:
        with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
            receiver.start_ppp(service=args.service)
            print(f"enabled PPP service: {args.service}", file=sys.stderr)
    epochs, first_fix, convergence, counts = _collect_epochs(args)
    payload = _payload(
        epochs,
        first_fix,
        convergence,
        args.horizontal_limit,
        args.vertical_limit,
    )
    payload["selection_counts"] = counts
    payload["freshness_source"] = (
        "host_clock_assumed_accurate" if args.trust_host_clock else "unavailable"
    )
    payload["convergence_censored"] = convergence is None
    summary = payload["summary"]
    if isinstance(summary, dict):
        print(
            f"Epochs: {summary['total_epochs']}; "
            f"converged: {summary['converged_epochs']}; "
            f"first fix: {summary['first_fix_s']}; "
            f"convergence: {summary['convergence_s']}",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
