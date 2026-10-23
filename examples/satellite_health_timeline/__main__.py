"""Report satellite health from ephemeris and visibility logs."""

from collections.abc import Sequence
from dataclasses import asdict

from um982py.capture import capture_records, record_epoch
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.messages import Record
from um982py.messages.gps_health import GpsLnavHealth
from um982py.messages.satellite_health import EphemerisHealth, GalileoEphemerisHealth


def decode_health(record: Record) -> list[dict[str, object]]:
    timestamp = record_epoch(record)
    if record.name == "GPSEPH":
        gps = GpsLnavHealth.from_record(record)
        return [
            {
                "epoch_gps_seconds": timestamp,
                "source": record.name,
                "system": "GPS",
                "satellite": gps.prn,
                "raw_health": gps.raw,
                "navigation_data_ok": gps.navigation_data_ok,
                "signal_status": gps.signal_status,
            }
        ]
    if record.name == "GALEPH":
        gal = GalileoEphemerisHealth.from_record(record)
        signals = {}
        for name in ("e1b", "e5a", "e5b"):
            signal = getattr(gal, name)
            signals[name] = {
                **asdict(signal),
                "health": signal.health.name if signal.health is not None else None,
                "data_validity": signal.data_validity.name
                if signal.data_validity is not None
                else None,
            }
        return [
            {
                "epoch_gps_seconds": timestamp,
                "source": record.name,
                "system": "Galileo",
                "satellite": gal.satellite_id,
                "signals": signals,
            }
        ]
    if record.name in ("GLOEPH", "BDSEPH", "BD3EPH"):
        eph = EphemerisHealth.from_record(record)
        return [
            {
                "epoch_gps_seconds": timestamp,
                "source": record.name,
                **asdict(eph),
                "healthy": eph.healthy,
            }
        ]
    if record.name == "SATELLITE":
        entries = []
        for row in record.records("satellites"):
            satellite_id = row["prn_slot"]
            if not isinstance(satellite_id, Record):
                raise ValueError("invalid satellite identifier")
            raw = row.integer("health")
            entries.append(
                {
                    "epoch_gps_seconds": timestamp,
                    "source": record.name,
                    "system": record["satellite_system"],
                    "satellite": satellite_id.integer("prn"),
                    "raw_health": raw,
                    "healthy": {0: True, 1: False}.get(raw),
                    "elevation_deg": row.real("elev"),
                    "azimuth_deg": row.real("az"),
                    "almanac_complete": record["comp_alm"],
                }
            )
        return entries
    raise ValueError("unsupported satellite health record")


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        description="Satellite health timeline from receiver reports"
    )
    add_receiver_arguments(parser)
    parser.add_argument("--duration", type=float, default=65)
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args(argv)
    paths = [path for path in (args.replay, args.record, args.json) if path is not None]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, recording and report paths must be distinct")
    logs = (Log.SATELLITE, Log.GPSEPH, Log.GALEPH, Log.GLOEPH, Log.BDSEPH, Log.BD3EPH)
    captured = capture_records(
        args, logs, duration=args.duration, interval=args.interval
    )
    events: list[dict[str, object]] = []
    rejected = []
    for name, records in captured.items():
        for record in records:
            try:
                events.extend(decode_health(record))
            except (ValueError, TypeError, KeyError) as error:
                rejected.append({"source": name, "error": str(error)})
    events.sort(key=lambda event: float(str(event["epoch_gps_seconds"])))
    if events:
        latest_epoch = float(str(events[-1]["epoch_gps_seconds"]))
        for event in events:
            event["age_since_log_at_last_event_seconds"] = latest_epoch - float(
                str(event["epoch_gps_seconds"])
            )
    write_json(
        {
            "status": "ok" if events else "no_usable_reports",
            "events": events,
            "rejected": rejected,
            "limitations": (
                "Receiver-reported states use the receiver log timestamp, while absent "
                "satellites and signals have unknown status. Galileo fields "
                "require the relevant navigation data. Age is measured from the "
                "log epoch to the final event, not the broadcast validity time."
            ),
        },
        args.json,
    )
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
