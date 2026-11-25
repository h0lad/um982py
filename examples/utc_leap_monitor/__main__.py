# Cross-check broadcast UTC parameters and announced leap seconds.

import sys
from collections.abc import Sequence
from datetime import timedelta

from examples._console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records
from examples.utc_leap_monitor import (
    UtcParameters,
    galileo_gps_offset,
    utc_parameters,
)
from um982py.commands import Log
from um982py.gnss import GPS_EPOCH, WEEK_SECONDS
from um982py.measurement import gps_epoch

_UTC_LOGS = (Log.IONUTC, Log.GALUTC, Log.BDSUTC)
_NANOSECONDS = 1e9


def _calendar(gps_seconds: float, leap_seconds: int) -> str:
    return (GPS_EPOCH + timedelta(seconds=gps_seconds - leap_seconds)).isoformat()


def _system_report(parameters: UtcParameters, epoch: float) -> dict[str, object]:
    leap = parameters.leap_seconds(epoch)
    announced = parameters.deltat_lsf != parameters.deltat_ls
    pending = announced and epoch < parameters.leap_epoch
    return {
        "gpst_minus_utc_s": leap,
        "deltat_ls": parameters.deltat_ls,
        "deltat_lsf": parameters.deltat_lsf,
        "leap_second_announced": pending,
        "leap_second_effective_utc": _calendar(
            parameters.leap_epoch, parameters.deltat_ls
        )
        if announced
        else None,
        "time_minus_utc_fraction_ns": parameters.fractional_offset(epoch)
        * _NANOSECONDS,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Report each system's UTC offset, pending leap second and agreement."""
    parser = experiment_parser(
        "utc_leap_monitor",
        "Broadcast UTC parameter and leap-second cross-check",
        output_rate=False,
    )
    parser.add_argument(
        "--tolerance-ns",
        type=float,
        default=20.0,
        help="allowed GGTO disagreement between broadcast and UTC-implied values",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "utc_leap_monitor")
    data = capture_records(
        args,
        [*_UTC_LOGS, Log.TIME],
        frames=1,
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("utc_leap_monitor") if args.debug else None,
    )
    parameters = {
        item.system: item
        for log in _UTC_LOGS
        for item in map(utc_parameters, data[log.value][-1:])
    }
    if not parameters:
        write_json(
            {
                "status": "insufficient_data",
                "reason": "no IONUTC, GALUTC or BDSUTC record was received",
            },
            args.json,
        )
        return 1
    times = data["TIME"]
    sources = times or tuple(
        record for log in _UTC_LOGS for record in data[log.value][-1:]
    )
    epoch = max(gps_epoch(record) for record in sources)
    systems = {name: _system_report(item, epoch) for name, item in parameters.items()}
    alarms = []
    leaps = {item.leap_seconds(epoch) for item in parameters.values()}
    if len(leaps) > 1:
        alarms.append("systems disagree on GPST minus UTC")
    announcements = {
        (item.deltat_lsf, item.leap_epoch)
        if item.deltat_lsf != item.deltat_ls and epoch < item.leap_epoch
        else None
        for item in parameters.values()
    }
    if len(announcements) > 1:
        alarms.append("systems announce different leap seconds")
    alarms.extend(
        f"{item.system} UTC reference time is over a week away"
        for item in parameters.values()
        if item.reference is not None and abs(epoch - item.reference) > WEEK_SECONDS
    )
    receiver_offset = times[-1].real("utc_offset") if times else None
    if receiver_offset is not None and -receiver_offset not in leaps:
        alarms.append("receiver TIME offset differs from broadcast leap seconds")
    ggto: dict[str, float] | None = None
    galileo = data["GALUTC"]
    if galileo and "GPS" in parameters and "GALILEO" in parameters:
        broadcast = galileo_gps_offset(galileo[-1], epoch) * _NANOSECONDS
        implied = (
            parameters["GALILEO"].fractional_offset(epoch)
            - parameters["GPS"].fractional_offset(epoch)
        ) * _NANOSECONDS
        ggto = {"broadcast_ns": broadcast, "utc_implied_ns": implied}
        if abs(broadcast - implied) > args.tolerance_ns:
            alarms.append("GGTO disagrees with the two UTC models")
    leap = min(leaps)
    write_json(
        {
            "status": "alarm" if alarms else "ok",
            "epoch_gps_seconds": epoch,
            "epoch_utc": _calendar(epoch, leap),
            "receiver_utc_offset_s": receiver_offset,
            "systems": systems,
            "galileo_gps_time_offset": ggto,
            "alarms": alarms,
        },
        args.json,
    )
    pending = [name for name, item in systems.items() if item["leap_second_announced"]]
    print(
        f"UTC monitor: GPST-UTC {leap} s from {', '.join(sorted(parameters))}; "
        + (
            f"leap second announced by {', '.join(pending)}"
            if pending
            else "no leap second announced"
        )
        + (f"; alarms: {'; '.join(alarms)}" if alarms else ""),
        file=sys.stderr,
    )
    return 1 if alarms else 0


if __name__ == "__main__":
    raise SystemExit(run(main))
