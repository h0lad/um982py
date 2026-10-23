"""Runs the interference monitor example from the command line."""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence

from examples.interference_monitor import (
    COLLAPSE_THRESHOLD,
    Alert,
    AntennaReport,
    SpoofReport,
    antenna_report,
    cn0_samples,
    detect_cn0_collapse,
    spoof_report,
    status_alerts,
)
from um982py.capture import capture_records
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def _alert_payload(alert: Alert) -> dict[str, object]:
    """Serialise one alert."""
    return {
        "epoch": alert.epoch,
        "kind": str(alert.kind),
        "severity": str(alert.severity),
        "satellites": list(alert.satellites),
        "z_score": _finite(alert.z_score),
    }


def _finite(z_score: float | None) -> float | None:
    """Drop an unbounded score so the payload stays valid JSON."""
    if z_score is None or not math.isfinite(z_score):
        return None
    return z_score


def _spoof_payload(report: SpoofReport | None) -> dict[str, object] | None:
    """Serialise the SPOOFINFO report."""
    if report is None:
        return None
    return {
        "position_type": report.position_type,
        "position_type_label": report.position_type_label,
        "spoof_indicator": report.spoof_indicator,
        "suspect": report.is_suspect,
    }


def _antenna_payload(report: AntennaReport | None) -> dict[str, object] | None:
    """Serialise the ANTENNA report."""
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
    """Build the monitoring payload from the decoded logs."""
    spoof = spoof_report(spoof_records[0]) if spoof_records else None
    antenna = antenna_report(antenna_records[0]) if antenna_records else None
    samples = cn0_samples(range_records)
    alerts = (
        *detect_cn0_collapse(samples, threshold=threshold),
        *status_alerts(max(len(range_records) - 1, 0), spoof, antenna),
    )
    return {
        "epochs": len(range_records),
        "cn0_scope": "GPS L1 C/A; epochs are record indices",
        "minimum_cn0_history_epochs": 5,
        "satellites": len({sample.satellite for sample in samples}),
        "spoof": _spoof_payload(spoof),
        "antenna": _antenna_payload(antenna),
        "alerts": [_alert_payload(alert) for alert in sorted(alerts, key=_order)],
    }


def _order(alert: Alert) -> tuple[int, str]:
    """Sort alerts by epoch and kind."""
    return (alert.epoch, str(alert.kind))


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
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "interference_monitor")
    captured = capture_records(
        args,
        [FirmwareLog.SPOOFINFO, FirmwareLog.ANTENNA, FirmwareLog.RANGE],
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
