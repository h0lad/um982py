"""Command-line receiver access and diagnostics."""

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from math import isfinite
from pathlib import Path

from um982py.antenna import antenna_log
from um982py.augmentation import enable_augmentation
from um982py.commands import queries
from um982py.diagnostics import (
    DOCTOR_LOGS,
    PPP_LOGS,
    RTK_LOGS,
    collect_diagnostics,
    doctor,
    ppp_diagnostics,
    rtk_diagnostics,
)
from um982py.errors import UM982Error
from um982py.experimental import (
    FirmwareLog,
    InternalDebugLog,
    capture_internal_debug,
    firmware_info,
    log_list,
    parse_mpt_debug,
    parse_pos_debug,
    parse_ppp_debug,
    performance_status,
    receiver_system_status,
)
from um982py.experimental.capture import RecordingTransport
from um982py.experimental.configuration import antenna_power_on
from um982py.experimental.raw_data import capture_baseband
from um982py.experimental.tracking import tracking_fields, tracking_slots
from um982py.receiver import Receiver
from um982py.rinex import export_rinex

_EXTENDED_ACTIONS = {
    "best-pos": FirmwareLog.BESTPOS,
    "psr-pos": FirmwareLog.PSRPOS,
    "rtk-pos": FirmwareLog.RTKPOS,
    "best-vel": FirmwareLog.BESTVEL,
    "time": FirmwareLog.TIME,
    "range": FirmwareLog.RANGE,
    "range-secondary": FirmwareLog.RANGEH,
    "heading-offset": FirmwareLog.HEADINGOFFSET,
    "pps-status": FirmwareLog.PPSSTATUS,
    "env-info": FirmwareLog.ENVINFO,
    "rx-status": FirmwareLog.RXSTATUS,
    "antenna": FirmwareLog.ANTENNA,
    "antenna-status": FirmwareLog.ANTENNASTATUS,
    "doppler-vel": FirmwareLog.DOPPVEL,
    "doppler-vel-secondary": FirmwareLog.DOPPVELH,
    "spoof-info": FirmwareLog.SPOOFINFO,
    "best-xyz": FirmwareLog.BESTXYZ,
    "sat-vis": FirmwareLog.SATVIS,
    "sat-vis-by-system": FirmwareLog.SATVIS2,
    "ref-station": FirmwareLog.REFSTATION,
    "psr-dop": FirmwareLog.PSRDOP,
    "psr-dop-secondary": FirmwareLog.PSRDOP2,
    "rtk-dop": FirmwareLog.RTKDOP,
    "rtk-dop-secondary": FirmwareLog.RTKDOP2,
    "rtk-vel": FirmwareLog.RTKVEL,
    "rtk-vel-secondary": FirmwareLog.RTKVEL2,
    "psr-vel": FirmwareLog.PSRVEL,
    "psr-vel-secondary": FirmwareLog.PSRVEL2,
}


def _json(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UM982 receiver client")
    parser.add_argument(
        "--port", default="/dev/ttyUSB0", help="serial device or tcp://host:port"
    )
    parser.add_argument(
        "--baud", type=int, default=115200, help="serial baud rate, ignored for TCP"
    )
    parser.add_argument("--timeout", type=float, default=3)
    parser.add_argument("--binary", action="store_true")
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
        choices=(
            "version",
            "config",
            "mode",
            "fix",
            "heading",
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
            range_log = FirmwareLog.RANGEH if antenna == 2 else FirmwareLog.RANGE
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
            capture = collect_diagnostics(receiver, logs, seconds=args.duration)
            if args.action == "doctor":
                return doctor(capture, antenna=antenna)
            if args.action == "rtk-diagnostics":
                return rtk_diagnostics(capture)
            return ppp_diagnostics(capture)
        case "tracking-info":
            record = receiver.execute(FirmwareLog.PTOBSINFO.read(binary=True))
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
                if log == FirmwareLog.SATVIS2
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
    if args.record and args.output and args.record.resolve() == args.output.resolve():
        parser.error("--record and --output need different paths")
    for path in (args.record, args.output):
        if path is not None and path.exists():
            parser.error(f"output already exists: {path}")
    recording = None
    try:
        with Receiver.connect(args.port, args.baud, timeout=args.timeout) as receiver:
            try:
                enable_augmentation(receiver)
            except (UM982Error, ValueError, OSError) as error:
                print(f"warning: augmentation not applied: {error}", file=sys.stderr)
            if args.record is not None:
                recording = RecordingTransport(receiver.transport, 32 * 1024 * 1024)
                receiver.transport = recording
            if args.action == "monitor":
                for _ in range(args.count):
                    print(json.dumps(receiver.receive(), default=_json))
            else:
                _write_result(_run_action(receiver, args, antenna), args)
    except (UM982Error, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if recording is not None and args.record is not None:
            args.record.parent.mkdir(parents=True, exist_ok=True)
            with args.record.open("xb") as stream:
                stream.write(recording.raw)
    return 0
