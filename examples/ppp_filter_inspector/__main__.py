"""Inspects live PPP filter residuals, SSR satellite counts and RTOS CPU load."""

import sys
from collections.abc import Sequence
from dataclasses import asdict

from examples.ppp_filter_inspector import analyse_ppp_filter
from um982py.capture import open_receiver, read_frames
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from um982py.experimental import (
    InternalDebugLog,
    PerformanceStatus,
    ReceiverSystemStatus,
    capture_internal_debug,
    parse_pos_debug,
    parse_ppp_debug,
)
from um982py.messages import AsciiMessage


def main(argv: Sequence[str] | None = None) -> int:
    """Capture or replay internal PPP filter telemetry and RTOS task utilization."""
    parser = experiment_parser(
        "ppp_filter_inspector",
        "Internal PPP filter SSR coverage, multifrequency residuals and CPU load",
    )
    parser.set_defaults(duration=4.0)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "ppp_filter_inspector")
    performance: PerformanceStatus | None = None
    system: ReceiverSystemStatus | None = None
    config_summary: dict[str, object] | None = None
    if args.replay is not None:
        raw = args.replay.read_bytes()
        for message in read_frames(args.replay):
            if isinstance(message, AsciiMessage) and message.name == "PERFSTATA":
                performance = PerformanceStatus.from_message(message)
            elif isinstance(message, AsciiMessage) and message.name == "RXSTATUSA":
                system = ReceiverSystemStatus.from_message(message)
    else:
        with open_receiver(args) as receiver:
            cfg = receiver.configuration()
            config_summary = {
                "signal_group": (
                    asdict(cfg.signal_group) if cfg.signal_group is not None else None
                ),
                "ppp_enabled": cfg.ppp_enabled,
                "ppp_service": cfg.ppp_service,
                "antenna_power": cfg.antenna_power,
            }
            performance = receiver.performance_status()
            system = receiver.system_status()
            ppp_log = (
                InternalDebugLog.PPP_DEBUG_SECONDARY
                if args.antenna in ("secondary", "2")
                else InternalDebugLog.PPP_DEBUG
            )
            ppp_cap = capture_internal_debug(receiver, ppp_log, seconds=args.duration)
            fast_cap = capture_internal_debug(
                receiver, InternalDebugLog.FAST_DEBUG, seconds=min(2.0, args.duration)
            )
            raw = ppp_cap.raw + b"\n" + fast_cap.raw
    lines = raw.splitlines()
    ppp_records = [
        ppp_item for line in lines if (ppp_item := parse_ppp_debug(line)) is not None
    ]
    pos_records = [
        pos_item for line in lines if (pos_item := parse_pos_debug(line)) is not None
    ]
    analysis = analyse_ppp_filter(ppp_records, pos_records, performance)
    usable = bool(ppp_records or pos_records or performance is not None)
    status = (
        "ppp_observed"
        if ppp_records
        else "auxiliary_telemetry_only"
        if usable
        else "no_debug_telemetry"
    )
    print(
        f"PPP filter: {len(ppp_records)} PPP epochs, "
        f"{len(pos_records)} position epochs; status={status}",
        file=sys.stderr,
    )
    write_json(
        {
            "status": status,
            "telemetry_sources": {
                "ppp_debug_epochs": len(ppp_records),
                "position_debug_epochs": len(pos_records),
                "performance_status": performance is not None,
            },
            "configuration": config_summary,
            "system_status": asdict(system) if system is not None else None,
            "performance": asdict(performance) if performance is not None else None,
            "analysis": asdict(analysis),
            "ppp_epochs": [asdict(item) for item in ppp_records],
            "pos_epochs": [asdict(item) for item in pos_records],
        },
        args.json,
    )
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
