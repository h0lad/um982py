# Monitor receiver jamming, spoofing and signal indicators.

from __future__ import annotations

import math
import sys
from collections.abc import Sequence

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_records
from examples.interference_monitor import (
    COLLAPSE_THRESHOLD,
    MINIMUM_SERIES,
    Alert,
    AntennaReport,
    antenna_report,
    cn0_samples,
    detect_cn0_collapse,
    status_alerts,
)
from um982py.commands import Log
from um982py.measurement import receiver_time
from um982py.messages import Record, SpoofInfo


def _gps_seconds(record: Record) -> float | None:
    time = receiver_time(record.message)
    return time.gps_seconds if time is not None else None


def _alert_payload(alert: Alert, record: Record) -> dict[str, object]:
    return {
        "epoch": alert.epoch,
        "gps_seconds": _gps_seconds(record),
        "source": record.name,
        "kind": str(alert.kind),
        "severity": str(alert.severity),
        "satellites": list(alert.satellites),
        "z_score": _finite_or_none(alert.z_score),
    }


def _finite_or_none(z_score: float | None) -> float | None:
    if z_score is None or not math.isfinite(z_score):
        return None
    return z_score


def _spoof_payload(report: SpoofInfo | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "position_type": report.position_type,
        "position_type_label": report.position_type_label,
        "spoof_indicator": report.indicator,
        "suspect": report.is_suspect,
        "notice_mask": int(report.notices),
        "time_notice_mask": int(report.time_notices),
        "signal_mask": int(report.signals),
        "gps_satellites": list(report.gps_satellites),
        "bds_satellites": list(report.bds_satellites),
        "galileo_satellites": list(report.galileo_satellites),
        "glonass_satellites": list(report.glonass_satellites),
    }


def _antenna_payload(report: AntennaReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "states": [str(report.state_1), str(report.state_2), str(report.state_3)],
        "degraded": report.is_degraded,
    }


def _payload(
    spoof_records: Sequence[Record],
    antenna_records: Sequence[Record],
    range_records: Sequence[Record],
    threshold: float,
) -> dict[str, object]:
    spoof = [SpoofInfo.from_record(record) for record in spoof_records]
    antenna = [antenna_report(record) for record in antenna_records]
    samples = cn0_samples(range_records)
    alerts = [
        (alert, range_records[alert.epoch])
        for alert in detect_cn0_collapse(samples, threshold=threshold)
    ]
    alerts.extend(
        (alert, record)
        for index, (report, record) in enumerate(zip(spoof, spoof_records, strict=True))
        for alert in status_alerts(index, report, None)
    )
    alerts.extend(
        (alert, record)
        for index, (report, record) in enumerate(
            zip(antenna, antenna_records, strict=True)
        )
        for alert in status_alerts(index, None, report)
    )
    return {
        "epochs": len(range_records),
        "cn0_scope": "GPS L1 C/A; session-wide per-satellite reference",
        "epoch_index": "zero-based index within each source log",
        "minimum_cn0_history_epochs": MINIMUM_SERIES,
        "satellites": len({sample.satellite for sample in samples}),
        "spoof": _spoof_payload(spoof[-1] if spoof else None),
        "spoof_gps_seconds": _gps_seconds(spoof_records[-1]) if spoof_records else None,
        "antenna": _antenna_payload(antenna[-1] if antenna else None),
        "antenna_gps_seconds": (
            _gps_seconds(antenna_records[-1]) if antenna_records else None
        ),
        "alerts": [
            _alert_payload(alert, record)
            for alert, record in sorted(alerts, key=_alert_order)
        ],
    }


def _alert_order(item: tuple[Alert, Record]) -> tuple[float, str, int]:
    alert, record = item
    when = _gps_seconds(record)
    return (when if when is not None else math.inf, str(alert.kind), alert.epoch)


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(
        prog="python -m examples.interference_monitor",
        description="Watch SPOOFINFO, ANTENNA and RANGE C/N0 for interference.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--threshold",
        type=float,
        default=COLLAPSE_THRESHOLD,
        help="robust z-score below which C/N0 counts as a collapse",
    )
    parser.add_argument(
        "--duration", type=float, default=5.0, help="live collection time in seconds"
    )
    parser.add_output_interval(default=1.0, help="output interval in seconds")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "interference_monitor")
    captured = capture_records(
        args,
        [Log.SPOOFINFO, Log.ANTENNA, Log.RANGE],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("interference_monitor") if args.debug else None,
    )
    if not any(captured.values()):
        parser.error("capture contains no SPOOFINFO, ANTENNA or RANGE records")
    payload = _payload(
        captured["SPOOFINFO"], captured["ANTENNA"], captured["RANGE"], args.threshold
    )
    alert_list = payload["alerts"]
    n_alerts = len(alert_list) if isinstance(alert_list, list) else 0
    print(
        f"Interference: {payload['epochs']} RANGE epochs, "
        f"{n_alerts} alert" + ("" if n_alerts == 1 else "s"),
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
