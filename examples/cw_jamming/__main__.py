"""Runs the continuous-wave jamming example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from examples.cw_jamming import (
    Band,
    BandFingerprint,
    CwState,
    JamAlert,
    JamSample,
    JamTimeline,
    alerts,
    band_samples,
    fingerprint,
    jam_state,
    timeline,
    worst_flag,
)
from um982py.capture import capture_records
from um982py.commands import Log
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    progress_printer,
    run,
    write_json,
)
from um982py.messages import Record


def _state_payload(state: CwState) -> dict[str, object]:
    """Serialise one jamming state with its documented class label."""
    return {
        "ratio": state.ratio,
        "flag": str(state.flag),
        "jammed": state.is_jammed,
    }


def _timeline_payload(summary: JamTimeline) -> dict[str, object]:
    """Serialise one aggregated series."""
    return {
        "epochs": summary.epochs,
        "jammed_epochs": summary.jammed_epochs,
        "worst_flag": str(summary.worst_flag),
        "peak_ratio": summary.peak_ratio,
        "first_jam_epoch": summary.first_jam_epoch,
    }


def _alert_payload(alert: JamAlert) -> dict[str, object]:
    """Serialise one class change."""
    return {
        "epoch": alert.epoch,
        "band": str(alert.band),
        "previous": str(alert.previous),
        "current": str(alert.current),
        "ratio": alert.ratio,
    }


def _summary_payload(records: Sequence[Record]) -> dict[str, object] | None:
    """Aggregate the JAMSTATUS series of one capture."""
    if not records:
        return None
    states = [jam_state(record) for record in records]
    return {
        **_state_payload(states[-1]),
        "timeline": _timeline_payload(timeline(states)),
    }


def _band_payload(samples: Sequence[JamSample]) -> list[dict[str, object]]:
    """Latest state, worst class and peak strength of every band of a capture."""
    owned: dict[str, list[JamSample]] = {}
    for sample in samples:
        owned.setdefault(str(sample.band), []).append(sample)
    return [
        {
            "band": band,
            **_state_payload(samples[-1].state),
            "worst_flag": str(worst_flag([sample.state.flag for sample in samples])),
            "peak_ratio": max(sample.state.ratio for sample in samples),
        }
        for band, samples in sorted(owned.items())
    ]


def _fingerprint_payload(item: BandFingerprint) -> dict[str, object]:
    """Serialise one epoch's source class and evidence."""
    return {
        "epoch": item.epoch,
        "interference": str(item.interference),
        "evidence": str(item.evidence),
        "jammed_bands": [str(band) for band in item.jammed_bands],
        "strongest": None if item.strongest is None else str(item.strongest),
    }


def _payload(
    summary_records: Sequence[Record], band_records: Sequence[Record]
) -> dict[str, object]:
    """Build the jamming report from the decoded logs."""
    samples = band_samples(band_records)
    by_epoch: dict[int, dict[Band, CwState]] = {}
    for sample in samples:
        by_epoch.setdefault(sample.epoch, {})[sample.band] = sample.state
    classified = [
        fingerprint(epoch, states) for epoch, states in sorted(by_epoch.items())
    ]
    fingerprints = [_fingerprint_payload(item) for item in classified]
    classes = [str(item.interference) for item in classified]
    return {
        "epochs": max(len(summary_records), len(band_records)),
        "summary": _summary_payload(summary_records),
        "bands": _band_payload(samples),
        "alerts": [_alert_payload(alert) for alert in alerts(samples)],
        "fingerprints": fingerprints,
        "interference_classes": sorted(set(classes)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Report the documented CW jamming classes of a capture or the device."""
    parser = ExampleParser(
        prog="python -m examples.cw_jamming",
        description="Report the JAMSTATUS and FREQJAMSTATUS CW jamming classes.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="collection time in seconds when reading the device",
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
    debug_header(args, "cw_jamming")
    captured = capture_records(
        args,
        [Log.JAMSTATUS, Log.FREQJAMSTATUS],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("cw_jamming") if args.debug else None,
    )
    payload = _payload(captured["JAMSTATUS"], captured["FREQJAMSTATUS"])
    if not payload["bands"] and payload["summary"] is None:
        write_json({"status": "insufficient_data", "payload": payload}, args.json)
        return 1
    print(
        f"CW jamming: {payload['epochs']} epochs, "
        f"classes {payload['interference_classes']}",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
