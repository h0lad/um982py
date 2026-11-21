# Inspects live PPP filter residuals, SSR satellite counts and RTOS CPU load.

import sys
from collections.abc import Sequence
from dataclasses import asdict

from examples._console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from examples._console_capture import open_receiver
from examples.ppp_filter_inspector import analyse_ppp_filter
from um982py.antenna import antenna_index
from um982py.capture import iter_frames
from um982py.experimental import (
    InternalDebugLog,
    capture_internal_debug,
    parse_pos_debug,
    parse_ppp_debug,
)
from um982py.messages import AsciiMessage, TextLine
from um982py.protocol import StreamDecoder
from um982py.receiver_models import PerformanceStatus, ReceiverSystemStatus


def main(argv: Sequence[str] | None = None) -> int:
    """Capture or replay internal PPP filter telemetry and RTOS task utilization."""
    parser = experiment_parser(
        "ppp_filter_inspector",
        "Internal PPP filter SSR coverage, multifrequency residuals and CPU load",
        output_rate=False,
    )
    parser.set_defaults(duration=4.0)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "ppp_filter_inspector")
    antenna = antenna_index(args.antenna)
    if args.swap_antennas:
        antenna = 3 - antenna
    ppp_log = (
        InternalDebugLog.PPP_DEBUG_SECONDARY
        if antenna == 2
        else InternalDebugLog.PPP_DEBUG
    )
    performance: PerformanceStatus | None = None
    system: ReceiverSystemStatus | None = None
    config_summary: dict[str, object] | None = None
    if args.replay is not None:
        frames = iter_frames(args.replay)
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
            ppp_cap = capture_internal_debug(receiver, ppp_log, seconds=args.duration)
            fast_cap = capture_internal_debug(
                receiver, InternalDebugLog.FAST_DEBUG, seconds=min(2.0, args.duration)
            )
            raw = ppp_cap.raw + b"\n" + fast_cap.raw
        frames = iter(StreamDecoder().feed(raw))
    ppp_records = []
    pos_records = []
    other_antenna_epochs = 0
    for message in frames:
        if isinstance(message, AsciiMessage) and message.name == "PERFSTATA":
            performance = PerformanceStatus.from_message(message)
        elif isinstance(message, AsciiMessage) and message.name == "RXSTATUSA":
            system = ReceiverSystemStatus.from_message(message)
        elif isinstance(message, TextLine):
            if (ppp_item := parse_ppp_debug(message.raw)) is not None:
                if ppp_item.source == ppp_log.value:
                    ppp_records.append(ppp_item)
                else:
                    other_antenna_epochs += 1
            if (pos_item := parse_pos_debug(message.raw)) is not None:
                pos_records.append(pos_item)
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
            "antenna": antenna,
            "ppp_debug_source": ppp_log.value,
            "telemetry_sources": {
                "ppp_debug_epochs": len(ppp_records),
                "other_antenna_ppp_debug_epochs": other_antenna_epochs,
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
