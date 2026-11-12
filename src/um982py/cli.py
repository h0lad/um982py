"""Command-line receiver access and diagnostics."""

import argparse
import json
import sys
from dataclasses import asdict, fields, is_dataclass
from enum import IntEnum
from math import isfinite
from pathlib import Path

from um982py.antenna import antenna_log
from um982py.augmentation import enable_augmentation
from um982py.capture import RecordingTransport
from um982py.commands import Log, logging, queries
from um982py.commands.types import Port
from um982py.diagnostics import (
    DOCTOR_LOGS,
    MADOCA_LOGS,
    PPP_LOGS,
    RTK_LOGS,
    collect_diagnostics,
    doctor,
    ppp_diagnostics,
    rtk_diagnostics,
)
from um982py.errors import UM982Error
from um982py.experimental import (
    InternalDebugLog,
    capture_internal_debug,
    parse_mpt_debug,
    parse_pos_debug,
    parse_ppp_debug,
)
from um982py.experimental.configuration import antenna_power_on
from um982py.experimental.raw_data import capture_baseband
from um982py.experimental.tracking import tracking_fields, tracking_slots
from um982py.messages.navigation import BestNavigation, Fix
from um982py.receiver import Receiver
from um982py.receiver_queries import (
    firmware_info,
    log_list,
    performance_status,
    receiver_system_status,
)
from um982py.rinex import export_rinex
from um982py.satellites import Satellite

_EXTENDED_ACTIONS = {
    "best-pos": Log.BESTPOS,
    "psr-pos": Log.PSRPOS,
    "rtk-pos": Log.RTKPOS,
    "best-vel": Log.BESTVEL,
    "time": Log.TIME,
    "range": Log.RANGE,
    "range-secondary": Log.RANGEH,
    "heading-offset": Log.HEADINGOFFSET,
    "pps-status": Log.PPSSTATUS,
    "env-info": Log.ENVINFO,
    "rx-status": Log.RXSTATUS,
    "antenna": Log.ANTENNA,
    "antenna-status": Log.ANTENNASTATUS,
    "doppler-vel": Log.DOPPVEL,
    "doppler-vel-secondary": Log.DOPPVELH,
    "spoof-info": Log.SPOOFINFO,
    "best-xyz": Log.BESTXYZ,
    "sat-vis": Log.SATVIS,
    "sat-vis-by-system": Log.SATVIS2,
    "ref-station": Log.REFSTATION,
    "psr-dop": Log.PSRDOP,
    "psr-dop-secondary": Log.PSRDOP2,
    "rtk-dop": Log.RTKDOP,
    "rtk-dop-secondary": Log.RTKDOP2,
    "rtk-vel": Log.RTKVEL,
    "rtk-vel-secondary": Log.RTKVEL2,
    "psr-vel": Log.PSRVEL,
    "psr-vel-secondary": Log.PSRVEL2,
}


def _json(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Fix):
        return {**asdict(value), "possibly_predicted": value.possibly_predicted}
    if isinstance(value, BestNavigation):
        return {
            item.name: (
                field.name
                if isinstance(field := getattr(value, item.name), IntEnum)
                else field
            )
            for item in fields(value)
            if item.name != "message"
        }
    if isinstance(value, Satellite):
        return {
            "constellation": value.constellation,
            "prn": value.prn,
            "azimuth_deg": value.azimuth_deg,
            "elevation_deg": value.elevation_deg,
            "signals": [
                {
                    "constellation": signal.constellation,
                    "name": signal.name,
                    "snr": signal.snr,
                    "system_id": signal.system_id,
                    "signal_id": signal.signal_id,
                }
                for signal in value.signals
            ],
        }
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and configure a UM982 receiver.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Common actions:\n"
            "  version          identify the receiver\n"
            "  fix              read a position\n"
            "  best-nav         read position, velocity and precision\n"
            "  heading          read dual-antenna heading\n"
            "  satellites       show tracked satellites and signals\n"
            "  output-rate      configure periodic log output\n"
            "  monitor          display incoming messages\n"
            "  rinex            capture and export observations\n"
            "  doctor           inspect receiver configuration and health\n"
            "  ppp-diagnostics  inspect PPP and correction delivery\n"
            "  rtk-diagnostics  inspect RTK status\n\n"
            "Use a serial port or tcp://host:port with --port."
        ),
    )
    parser.add_argument(
        "--port", default="/dev/ttyUSB0", help="serial device or tcp://host:port"
    )
    parser.add_argument(
        "--baud", type=int, default=115200, help="serial baud rate, ignored for TCP"
    )
    parser.add_argument("--timeout", type=float, default=3)
    parser.add_argument("--binary", action="store_true")
    parser.add_argument(
        "--madoca",
        action="store_true",
        help="include QZSS MADOCA correction logs in PPP diagnostics",
    )
    parser.add_argument(
        "--augment",
        action="store_true",
        help="enable augmentation; signal group changes are saved by the receiver",
    )
    parser.add_argument(
        "--sbas-service",
        type=str.upper,
        metavar="SERVICE",
        help="select the SBAS service with --augment; use QZSS for SLAS",
    )
    parser.add_argument(
        "--antenna",
        choices=("primary", "secondary", "1", "2"),
        default="primary",
        help="select ANT1 or ANT2 measurements while receiver-wide and "
        "dual-antenna logs retain their scope",
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument(
        "--log",
        type=Log,
        action="append",
        help="log to configure; repeat for multiple logs",
    )
    parser.add_argument("--rate-hz", type=float, help="periodic log output rate in Hz")
    parser.add_argument(
        "--output-port", type=Port, choices=list(Port), help="receiver output port"
    )
    parser.add_argument(
        "--verify-rate", action="store_true", help="verify settings through LOGLIST"
    )
    parser.add_argument(
        "--l2c-code",
        choices=("2S", "2L", "2X"),
        help="choose a RINEX component for type-9 L2C, otherwise omitted as unverified",
    )
    parser.add_argument(
        "--record", type=Path, help="save live received bytes (new file)"
    )
    parser.add_argument("--output", type=Path, help="write JSON to a new file")
    parser.add_argument(
        "action",
        metavar="ACTION",
        help="receiver action; see common actions below",
        choices=(
            "version",
            "config",
            "mode",
            "fix",
            "heading",
            "satellites",
            "output-rate",
            "best-nav",
            "fw-info",
            "log-list",
            "monitor",
            "antenna-power-on",
            "doctor",
            "rtk-diagnostics",
            "ppp-diagnostics",
            "ppp-debug",
            "fast-debug",
            "mpt-debug",
            "perf-stat",
            "system-status",
            "tracking-info",
            "rinex",
            "baseband-audit",
            *_EXTENDED_ACTIONS,
        ),
    )
    return parser


def _run_action(receiver: Receiver, args: argparse.Namespace, antenna: int) -> object:
    match args.action:
        case "output-rate":
            output_logs = [antenna_log(log, args.antenna) for log in args.log]
            responses = receiver.set_output_rate(
                output_logs,
                args.rate_hz,
                binary=args.binary,
                port=args.output_port,
                verify=args.verify_rate,
            )
            return {
                "rate_hz": args.rate_hz,
                "commands": [response.command for response in responses],
                "readback_verified": args.verify_rate,
                "actual_rate_measured": False,
            }
        case "ppp-debug" | "fast-debug" | "mpt-debug":
            debug_log = {
                "ppp-debug": InternalDebugLog.PPP_DEBUG_SECONDARY
                if antenna == 2
                else InternalDebugLog.PPP_DEBUG,
                "fast-debug": InternalDebugLog.FAST_DEBUG,
                "mpt-debug": InternalDebugLog.MPT_DEBUG,
            }[args.action]
            debug_capture = capture_internal_debug(
                receiver, debug_log, seconds=args.duration
            )
            lines = debug_capture.raw.splitlines()
            if args.action == "ppp-debug":
                parsed_items: list[object] = [
                    asdict(ppp_item)
                    for line in lines
                    if (ppp_item := parse_ppp_debug(line)) is not None
                ]
            elif args.action == "fast-debug":
                parsed_items = [
                    asdict(pos_item)
                    for line in lines
                    if (pos_item := parse_pos_debug(line)) is not None
                ]
            else:
                parsed_items = [
                    asdict(mpt_item)
                    for line in lines
                    if (mpt_item := parse_mpt_debug(line)) is not None
                ]
            return {
                **debug_capture.manifest(),
                "records": parsed_items,
            }
        case "baseband-audit":
            baseband = capture_baseband(
                receiver, seconds=args.duration, enable_gate=False
            )
            return {
                **baseband.manifest(),
                "status": "containers_observed"
                if baseband.packets
                else "no_containers_observed",
                "iq_samples_verified": False,
            }
        case "rinex":
            range_log = Log.RANGEH if antenna == 2 else Log.RANGE
            capture = collect_diagnostics(receiver, (range_log,), seconds=args.duration)
            return export_rinex(
                capture.records[range_log.value], l2c_code=args.l2c_code
            ).text
        case "doctor" | "rtk-diagnostics" | "ppp-diagnostics":
            logs = {
                "doctor": DOCTOR_LOGS,
                "rtk-diagnostics": RTK_LOGS,
                "ppp-diagnostics": PPP_LOGS,
            }[args.action]
            if args.action == "ppp-diagnostics" and args.madoca:
                logs = (*logs, *MADOCA_LOGS)
            capture = collect_diagnostics(receiver, logs, seconds=args.duration)
            if args.action == "doctor":
                return doctor(capture, antenna=antenna)
            if args.action == "rtk-diagnostics":
                return rtk_diagnostics(capture)
            return ppp_diagnostics(capture)
        case "tracking-info":
            record = receiver.execute(Log.PTOBSINFO.read(binary=True))
            return {
                "source": record.name,
                "baseband_source_message_id": 24,
                "semantics": "slot_values_recorded_units_unverified",
                "fields": [asdict(f) for f in tracking_fields(record)],
                "slots": [asdict(slot) for slot in tracking_slots(record)],
            }
        case "version":
            return receiver.version(binary=args.binary)
        case "config":
            return receiver.collect(queries.configuration())
        case "mode":
            return receiver.execute(queries.mode())
        case "fix":
            return receiver.execute(queries.fix(antenna=antenna))
        case "heading":
            return receiver.execute(queries.heading())
        case "satellites":
            return receiver.satellites()
        case "antenna-power-on":
            return receiver.execute(antenna_power_on())
        case "best-nav":
            return receiver.execute(
                queries.best_navigation(binary=args.binary, antenna=antenna)
            )
        case "fw-info":
            return receiver.execute(firmware_info(binary=args.binary))
        case "perf-stat":
            return receiver.execute(performance_status())
        case "system-status":
            return receiver.execute(receiver_system_status())
        case "log-list":
            return receiver.execute(log_list())
        case name if name in _EXTENDED_ACTIONS:
            log = antenna_log(_EXTENDED_ACTIONS[name], args.antenna)
            command = log.read(binary=args.binary)
            return (
                receiver.collect(command)
                if log == Log.SATVIS2
                else receiver.execute(command)
            )
        case _:
            raise ValueError(f"Unsupported action: {args.action}")


def _write_result(outcome: object, args: argparse.Namespace) -> None:
    encoded = (
        str(outcome)
        if args.action == "rinex"
        else json.dumps(outcome, default=_json, indent=2, allow_nan=False)
    )
    if args.output is None:
        print(encoded)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    antenna = 2 if args.antenna in ("secondary", "2") else 1
    if args.count < 1:
        parser.error("--count must be positive")
    if not isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration must be finite and positive")
    if args.sbas_service is not None and not args.augment:
        parser.error("--sbas-service requires --augment")
    if args.madoca and args.action != "ppp-diagnostics":
        parser.error("--madoca requires ppp-diagnostics")
    if args.action == "output-rate":
        if not args.log or args.rate_hz is None:
            parser.error("output-rate requires --log and --rate-hz")
        if args.verify_rate and args.output_port is None:
            parser.error("--verify-rate requires --output-port")
        try:
            logging.interval_from_rate(args.rate_hz)
        except ValueError as error:
            parser.error(str(error))
    if args.record and args.output and args.record.resolve() == args.output.resolve():
        parser.error("--record and --output need different paths")
    for path in (args.record, args.output):
        if path is not None and path.exists():
            parser.error(f"output already exists: {path}")
    try:
        with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
            if args.augment:
                state = (
                    enable_augmentation(receiver)
                    if args.sbas_service is None
                    else enable_augmentation(receiver, sbas_service=args.sbas_service)
                )
                if state.rejected:
                    refused = ", ".join(name for name, _ in state.rejected)
                    print(f"warning: augmentation refused: {refused}", file=sys.stderr)
            if args.record is not None:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                stream = args.record.open("xb")
                receiver.transport = RecordingTransport(receiver.transport, stream)
            if args.action == "monitor":
                for _ in range(args.count):
                    print(json.dumps(receiver.receive(), default=_json))
            else:
                _write_result(_run_action(receiver, args, antenna), args)
    except (UM982Error, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        for note in getattr(error, "__notes__", ()):
            print(note, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0
