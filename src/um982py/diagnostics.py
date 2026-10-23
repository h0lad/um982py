"""Receiver and active-antenna diagnostics in receiver units."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from statistics import median
from time import monotonic

from um982py._firmware_logs import FirmwareLog
from um982py.commands import Log, Trigger, logging, queries
from um982py.corrections import audit_corrections, audit_has, correction_events
from um982py.errors import ResponseTimeout
from um982py.measurement import gps_epoch
from um982py.messages import Record, Sentence
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.receiver import Receiver
from um982py.receiver_queries import log_list
from um982py.signals import tracking_signal
from um982py.subscriptions import temporary_subscriptions

type DiagnosticLog = Log | FirmwareLog

DOCTOR_LOGS: tuple[DiagnosticLog, ...] = (
    FirmwareLog.RANGE,
    FirmwareLog.RANGEH,
    FirmwareLog.ANTENNASTATUS,
    Log.AGC,
    Log.HWSTATUS,
    FirmwareLog.TIME,
    Log.BESTNAV,
    Log.BESTNAVH,
)
RTK_LOGS: tuple[DiagnosticLog, ...] = (
    Log.RTKSTATUS,
    FirmwareLog.RTKSTATUS2,
    FirmwareLog.RTKSTATUSD,
    FirmwareLog.RTKSTATUS2D,
    Log.RTCMSTATUS,
    Log.BESTNAV,
    Log.BESTNAVH,
    FirmwareLog.BESTSATS,
)
PPP_LOGS: tuple[DiagnosticLog, ...] = (
    Log.PPPNAV,
    Log.PPPDOP,
    *(Log[f"PPPB2BINFO{i}"] for i in range(1, 8)),
    Log.E6MASKBLOCK,
    Log.E6ORBITBLOCK,
    Log.E6CLOCKFULLBLOCK,
    Log.E6CLOCKSUBBLOCK,
    Log.E6CBIASBLOCK,
    Log.E6PBIASBLOCK,
)


@dataclass(frozen=True, slots=True)
class DiagnosticCapture:
    records: dict[str, tuple[Record, ...]]
    duration_seconds: float
    subscriptions_restored: bool
    configuration_restored: bool
    configuration: tuple[tuple[str, ...], ...]
    arrival_order: tuple[Record, ...] = ()


def collect_diagnostics(
    receiver: Receiver,
    logs: Sequence[DiagnosticLog] = DOCTOR_LOGS,
    *,
    seconds: float = 5.0,
) -> DiagnosticCapture:
    """Collect timestamped evidence and restore the original output state."""
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be finite and positive")
    if len({log.value for log in logs}) != len(logs):
        raise ValueError("diagnostic logs must be unique")
    before = receiver.execute(log_list())
    config = tuple(
        sorted(
            {
                message.fields
                for message in receiver.collect(queries.configuration())
                if isinstance(message, Sentence)
            }
        )
    )
    planned = []
    for log in logs:
        interval: float | Trigger = 1.0
        if log in (Log.RTCMSTATUS, *PPP_LOGS[2:]):
            interval = Trigger.ON_CHANGED
        try:
            start = log.output(interval, binary=True)
        except ValueError:
            start = log.output(Trigger.ON_CHANGED, binary=True)
        planned.append((log.wire_name(binary=True), start))
    records: dict[str, list[Record]] = {log.value: [] for log in logs}
    arrival_order: list[Record] = []
    matchers = [
        logging.request(
            log.wire_name(binary=True),
            message_id=log.definition.message_id if isinstance(log, Log) else None,
        )
        if isinstance(log, Log)
        else log.request(binary=True)
        for log in logs
    ]
    started = monotonic()
    with temporary_subscriptions(receiver, *planned):
        deadline = monotonic() + seconds
        while (remaining := deadline - monotonic()) > 0:
            try:
                message = receiver.receive(timeout=min(receiver.timeout, remaining))
            except ResponseTimeout:
                continue
            for log, matcher in zip(logs, matchers, strict=True):
                if matcher.matches(message):
                    record = log.decode(message)
                    records[log.value].append(record)
                    arrival_order.append(record)
    restored = receiver.execute(log_list())
    final_config = tuple(
        sorted(
            {
                message.fields
                for message in receiver.collect(queries.configuration())
                if isinstance(message, Sentence)
            }
        )
    )
    return DiagnosticCapture(
        {name: tuple(values) for name, values in records.items()},
        monotonic() - started,
        set(restored.entries) == set(before.entries),
        config == final_config,
        config,
        tuple(arrival_order),
    )


def _latest(capture: DiagnosticCapture, name: str) -> dict[str, object] | None:
    records = capture.records.get(name, ())
    return dict(records[-1]) if records else None


def signal_inventory(records: Sequence[Record]) -> list[dict[str, object]]:
    """Describe every wire signal, retaining unknown identifiers and raw channels."""
    groups: dict[tuple[int, int, bool], list[Record]] = {}
    for record in records:
        for obs in record.records("observations"):
            status = obs.integer("tracking_status")
            key = (status >> 16 & 7, status >> 21 & 31, bool(status & (1 << 26)))
            groups.setdefault(key, []).append(obs)
    result: list[dict[str, object]] = []
    for (system, signal, l2c), observations in sorted(groups.items()):
        identified = tracking_signal(observations[0].integer("tracking_status"))
        cn0 = [o.real("cn0") for o in observations if isfinite(o.real("cn0"))]
        result.append(
            {
                "system": system,
                "signal": signal,
                "l2c_flag": l2c,
                "identification": asdict(identified) if identified else None,
                "observations": len(observations),
                "satellites": len({o.integer("prn") for o in observations}),
                "code_and_phase_valid": sum(
                    o.integer("tracking_status") & 0x1400 == 0x1400
                    for o in observations
                ),
                "median_cn0_db_hz": median(cn0) if cn0 else None,
                "wire_frequency_channels": sorted(
                    {o.integer("frequency_channel") for o in observations}
                ),
            }
        )
    return result


def doctor(capture: DiagnosticCapture, *, antenna: int = 1) -> dict[str, object]:
    """Report both RF inputs and clearly separate power configuration from health."""
    if antenna not in (1, 2):
        raise ValueError("antenna must be 1 or 2")
    antennas = []
    for number, name, nav in ((1, "RANGE", "BESTNAV"), (2, "RANGEH", "BESTNAVH")):
        records = capture.records.get(name, ())
        antennas.append(
            {
                "antenna": number,
                "range_source": name,
                "epochs": len(records),
                "latest_observations": records[-1].integer("count") if records else 0,
                "signals": signal_inventory(records),
                "navigation": _latest(capture, nav),
                "receiving": bool(records and records[-1].integer("count")),
            }
        )
    return {
        "selected_antenna": antenna,
        "antennas": antennas,
        "antenna_power_configuration": [
            row for row in capture.configuration if row[:1] == ("ANTENNA",)
        ],
        "antenna_status_raw": _latest(capture, "ANTENNASTATUS"),
        "agc_receiver_units": _latest(capture, "AGC"),
        "hardware_status": _latest(capture, "HWSTATUS"),
        "time": _latest(capture, "TIME"),
        "bias_voltage_measured": False,
        "subscriptions_restored": capture.subscriptions_restored,
        "configuration_restored": capture.configuration_restored,
    }


def rtk_diagnostics(capture: DiagnosticCapture) -> dict[str, object]:
    """Distinguish absent correction telemetry from a diagnosed RTK fix failure."""
    corrections = capture.records.get("RTCMSTATUS", ())
    messages = Counter(record.integer("msg_id") for record in corrections)
    return {
        "status": "correction_telemetry_observed"
        if corrections
        else "no_correction_telemetry_observed",
        "rtcm_message_events": dict(messages),
        "base_ids": sorted({r.integer("base_id") for r in corrections}),
        "rtk_status": {
            name: _latest(capture, name)
            for name in ("RTKSTATUS", "RTKSTATUS2", "RTKSTATUSD", "RTKSTATUS2D")
        },
        "navigation": {
            name: _latest(capture, name) for name in ("BESTNAV", "BESTNAVH")
        },
        "capture_seconds": capture.duration_seconds,
        "subscriptions_restored": capture.subscriptions_restored,
        "configuration_restored": capture.configuration_restored,
        "absolute_accuracy_verified": False,
    }


def ppp_diagnostics(capture: DiagnosticCapture) -> dict[str, object]:
    """Report native B2b delivery and PPP solutions without inferring application."""
    records = capture.arrival_order or tuple(
        sorted(
            (
                r
                for name, rows in capture.records.items()
                if name.startswith(("PPPB2BINFO", "E6"))
                for r in rows
            ),
            key=lambda r: gps_epoch(r.message) if r.message is not None else 0,
        )
    )
    events = [r for r in records if r.name.startswith("PPPB2BINFO")]
    checks = audit_corrections(
        [event for record in events for event in correction_events(record)]
    )
    has_records = [r for r in records if r.name.startswith("E6")]
    navigation = _latest(capture, "PPPNAV")
    position_label = solution_label = None
    if navigation is not None:
        try:
            position_label = PositionType(int(str(navigation["pos_type"]))).name
        except ValueError:
            position_label = str(navigation["pos_type"])
        try:
            solution_label = SolutionStatus(int(str(navigation["sol_status"]))).name
        except ValueError:
            solution_label = str(navigation["sol_status"])
    signal_group = next(
        (
            row[1].split()[2:]
            for row in capture.configuration
            if row[:1] == ("SIGNALGROUP",) and len(row) > 1
        ),
        None,
    )
    return {
        "status": "correction_telemetry_observed"
        if (events or has_records)
        else "no_correction_telemetry_observed",
        "correction_records": dict(Counter(r.name for r in events)),
        "correction_receive_gps_epochs": [
            gps_epoch(r.message) for r in events if r.message is not None
        ],
        "navigation": navigation,
        "position_type_label": position_label,
        "solution_status_label": solution_label,
        "signal_group": signal_group,
        "b2b_documented_signal_group_met": signal_group == ["3", "6"],
        "receiver_reports_ppp": position_label
        in ("PPP_CONVERGING", "PPP", "PPP_AR", "PPP_RTK"),
        "dop": _latest(capture, "PPPDOP"),
        "correction_application_verified": False,
        "coherence_checks": [asdict(check) for check in checks],
        "has_records": dict(Counter(r.name for r in has_records)),
        "has_coherence_checks": audit_has(has_records),
        "subscriptions_restored": capture.subscriptions_restored,
        "configuration_restored": capture.configuration_restored,
    }
