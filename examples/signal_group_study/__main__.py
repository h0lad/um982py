"""Runs the signal-group trade study from the command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from time import sleep

from examples.dop_geometry import (
    DilutionOfPrecision,
    ReportedDilution,
    SatelliteGeometry,
    geometry_from_records,
)
from examples.rtk_quality import position_type_code
from examples.signal_group_study import (
    SettingSample,
    SettingSummary,
    first_visibility_epoch,
    trade_study,
)
from um982py.antenna import antenna_log
from um982py.capture import DataLog, open_receiver, read_frames, receive_records
from um982py.commands.configuration import (
    SignalGroup,
    current_signal_group,
    signal_group,
)
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.errors import UM982Error
from um982py.experimental import FirmwareLog
from um982py.geodesy import records_from
from um982py.messages import Message
from um982py.messages.enums import PositionType
from um982py.messages.record import Record
from um982py.state import restore_receiver_state, snapshot_receiver_state
from um982py.subscriptions import temporary_subscriptions

DEFAULT_SETTINGS = ((4, 5), (3, 6))
ZENITH = SatelliteGeometry(0.0, 90.0)
HORIZON = (
    SatelliteGeometry(0.0, 0.0),
    SatelliteGeometry(90.0, 0.0),
    SatelliteGeometry(180.0, 0.0),
    SatelliteGeometry(270.0, 0.0),
)
WIDE_SKY = (ZENITH,) * 4 + HORIZON
NARROW_SKY = WIDE_SKY[:-1]
WIDE_CN0 = (45.0, 44.5, 46.0, 43.5, 39.0, 38.5, 40.0, 39.5)
NARROW_CN0 = (45.0, 44.5, 46.0, 43.5, 39.0, 38.5, 40.0)


def injected_dilution(geometry: Sequence[SatelliteGeometry]) -> ReportedDilution:
    """Reported DOP of an injected sky, taken from the same geometry."""
    dilutions = DilutionOfPrecision.from_geometry(geometry)
    return ReportedDilution(
        source="injected",
        gdop=dilutions.gdop,
        pdop=dilutions.pdop,
        hdop=dilutions.hdop,
        tdop=dilutions.tdop,
        elevation_mask=0.0,
        satellites=len(geometry),
    )


def injected_samples() -> tuple[SettingSample, ...]:
    """Injected settings where the wider group sees one more horizon satellite."""
    return (
        SettingSample(
            setting=SignalGroup(4, 5),
            geometry=WIDE_SKY,
            reported=injected_dilution(WIDE_SKY),
            cn0=WIDE_CN0,
            position_type=PositionType.NARROW_INT,
        ),
        SettingSample(
            setting=SignalGroup(5, 0),
            geometry=NARROW_SKY,
            reported=injected_dilution(NARROW_SKY),
            cn0=NARROW_CN0,
            position_type=PositionType.NARROW_FLOAT,
        ),
    )


def cn0_from(records: Sequence[Record]) -> tuple[float, ...]:
    """C/N0 in dB-Hz of every signal of the collected RANGE frames."""
    return tuple(
        observation.real("cn0")
        for record in records
        for observation in records_from(record, "observations")
    )


def frames_of(frames: Sequence[Message], log: DataLog) -> list[Record]:
    """Decode every frame of a transcript that carries the given firmware log."""
    records = []
    for message in frames:
        for binary in (False, True):
            if log.request(binary=binary).matches(message):
                records.append(log.decode(message))
                break
    return records


def replay_samples(args: argparse.Namespace) -> tuple[SettingSample, ...]:
    """One setting per signal group named in a captured transcript."""
    frames = read_frames(args.replay)
    sky = frames_of(frames, FirmwareLog.SATVIS2)
    dop_records = frames_of(
        frames, antenna_log(FirmwareLog.PSRDOP, getattr(args, "antenna", "primary"))
    )
    positions = frames_of(
        frames, antenna_log(FirmwareLog.BESTPOS, getattr(args, "antenna", "primary"))
    )
    if not sky or not dop_records or not positions:
        raise ValueError("replay requires SATVIS2, PSRDOP and BESTPOS records")
    dilution = ReportedDilution.from_record(dop_records[0], "PSRDOP")
    ranges = frames_of(
        frames, antenna_log(FirmwareLog.RANGE, getattr(args, "antenna", "primary"))
    )
    best = positions[0]
    sample = SettingSample(
        setting=SignalGroup(args.replay_master, args.replay_slave),
        geometry=geometry_from_records(
            first_visibility_epoch(sky), dilution.elevation_mask
        ),
        reported=dilution,
        cn0=cn0_from(ranges),
        position_type=position_type_code(best),
    )
    return (sample,)


def measure_setting(args: argparse.Namespace, setting: SignalGroup) -> SettingSample:
    """Select a signal group, wait out the reboot, then sample the resulting sky."""
    range_log = antenna_log(FirmwareLog.RANGE, getattr(args, "antenna", "primary"))
    position_log = antenna_log(FirmwareLog.BESTPOS, getattr(args, "antenna", "primary"))
    dop_log = antenna_log(FirmwareLog.PSRDOP, getattr(args, "antenna", "primary"))
    print(
        f"Selecting group {setting.master}/{setting.slave}; "
        f"reboot wait {args.reboot_seconds:g}s...",
        file=sys.stderr,
        flush=True,
    )
    with open_receiver(args) as receiver:
        receiver.send(signal_group(setting.master, setting.slave))
    sleep(args.reboot_seconds)
    with (
        open_receiver(args) as receiver,
        temporary_subscriptions(
            receiver,
            (
                FirmwareLog.SATVIS2.wire_name(),
                FirmwareLog.SATVIS2.output(args.interval),
            ),
            (
                dop_log.wire_name(),
                dop_log.output(args.interval),
            ),
            (
                range_log.wire_name(),
                range_log.output(args.interval),
            ),
            (
                position_log.wire_name(),
                position_log.output(args.interval),
            ),
        ),
    ):
        print(
            f"Collecting {args.frames} epochs for this group...",
            file=sys.stderr,
            flush=True,
        )
        captured = receive_records(
            receiver,
            [
                FirmwareLog.SATVIS2,
                dop_log,
                range_log,
                position_log,
            ],
            duration=args.frames * args.interval + args.timeout,
            show_progress=True,
        )
        sky, ranges = captured["SATVIS2"], captured["RANGE"]
        if not sky or not captured["PSRDOP"] or not captured["BESTPOS"]:
            raise ValueError("receiver did not supply SATVIS2, PSRDOP and BESTPOS")
        dop_record, best = captured["PSRDOP"][0], captured["BESTPOS"][0]
    dilution = ReportedDilution.from_record(dop_record, "PSRDOP")
    return SettingSample(
        setting=setting,
        geometry=geometry_from_records(
            first_visibility_epoch(sky), dilution.elevation_mask
        ),
        reported=dilution,
        cn0=cn0_from(ranges),
        position_type=position_type_code(best),
    )


def live_study(args: argparse.Namespace) -> dict[str, object]:
    """Sample every requested setting and restore the original one."""
    with open_receiver(args) as receiver:
        original = receiver.execute(current_signal_group())
        before = snapshot_receiver_state(receiver)
    try:
        samples = [
            measure_setting(args, SignalGroup(master, slave))
            for master, slave in args.settings
        ]
    finally:
        print(
            f"Restoring group {original.master}/{original.slave}...",
            file=sys.stderr,
            flush=True,
        )
        with open_receiver(args) as receiver:
            receiver.send(signal_group(original.master, original.slave))
        sleep(args.reboot_seconds)
        with open_receiver(args) as receiver:
            restored = receiver.execute(current_signal_group())
            result = restore_receiver_state(receiver, before)
        if restored != original or not result.restored:
            raise UM982Error(
                f"Receiver state was not restored: group={restored}, "
                f"differences={result.differences}, errors={result.errors}"
            )
    return table_payload(trade_study(samples), result.differences)


def row_payload(summary: SettingSummary) -> dict[str, object]:
    """Serialise one trade-study row."""
    return {
        "master": summary.setting.master,
        "slave": summary.setting.slave,
        "master_bands": summary.setting.master_bands,
        "satellites": summary.satellites,
        "signals": summary.signals,
        "mean_cn0": summary.mean_cn0,
        "gdop": summary.dilutions.gdop,
        "pdop": summary.dilutions.pdop,
        "hdop": summary.dilutions.hdop,
        "reported_pdop": summary.reported_pdop,
        "pdop_excess": summary.pdop_excess,
        "agreement": summary.agreement,
        "fix_class": summary.fix_class,
    }


def table_payload(
    summaries: Sequence[SettingSummary], changed: Sequence[str] | None
) -> dict[str, object]:
    """Serialise the trade-study rows and the restore check."""
    return {
        "settings": [row_payload(summary) for summary in summaries],
        "restore": None if changed is None else {"changed": list(changed)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the trade study live, from a transcript, or over the injected table."""
    parser = ExampleParser(
        prog="python -m examples.signal_group_study",
        description="Trade study across CONFIG SIGNALGROUP settings",
    )
    add_receiver_arguments(parser)
    parser.set_defaults(port=None)
    parser.add_argument(
        "--settings",
        type=int,
        nargs=2,
        action="append",
        default=None,
        help="master and slave group numbers of one setting, repeatable",
    )
    parser.add_argument(
        "--frames", type=int, default=30, help="number of RANGE frames per setting"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--reboot-seconds",
        type=float,
        default=20.0,
        help="seconds to wait for the module to reboot after SIGNALGROUP",
    )
    parser.add_argument(
        "--replay-master",
        type=int,
        default=4,
        help="signal group the replayed transcript was captured with",
    )
    parser.add_argument(
        "--replay-slave", type=int, default=5, help="slave group of the transcript"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "signal_group_study")
    args.settings = DEFAULT_SETTINGS if args.settings is None else args.settings
    if args.port is not None:
        result = live_study(args)
    elif args.replay is not None:
        result = table_payload(trade_study(replay_samples(args)), None)
    else:
        result = table_payload(trade_study(injected_samples()), None)
    result["source"] = (
        "live"
        if args.port is not None
        else "replay"
        if args.replay is not None
        else "synthetic"
    )
    rows = result.get("settings")
    print(
        f"Signal groups: "
        f"{len(rows) if isinstance(rows, list) else 0} settings "
        f"({result['source']})",
        file=sys.stderr,
    )
    write_json(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
