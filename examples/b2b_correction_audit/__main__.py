"""Audits a PPP-B2b correction stream from the command line."""

import csv
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.b2b_correction_audit import (
    align_navigation,
    audit_corrections,
    chronological,
    service_census,
)
from um982py.capture import capture_logs
from um982py.commands import Log
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    read_numeric_csv,
    run,
    write_json,
)
from um982py.corrections import audit_has, correction_events
from um982py.field_data import file_sha256
from um982py.messages import Record

LOGS = tuple(Log[f"PPPB2BINFO{i}"] for i in range(1, 8))
HAS_LOGS = (
    Log.E6MASKBLOCK,
    Log.E6ORBITBLOCK,
    Log.E6CLOCKFULLBLOCK,
    Log.E6CLOCKSUBBLOCK,
    Log.E6CBIASBLOCK,
    Log.E6PBIASBLOCK,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Audit ages and issue consistency while retaining missing reference checks."""
    parser = experiment_parser(
        "b2b_correction_audit", "PPP-B2b correction age, mask and issue coherence"
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=60.0,
        help="experiment correction-age limit, seconds",
    )
    parser.add_argument("--mask-max-age", type=float, default=300.0)
    parser.add_argument(
        "--checks-csv", type=Path, help="write PPP-B2b checks per message"
    )
    parser.add_argument(
        "--navigation",
        type=Path,
        help="independent slot,iodn CSV using native PPP-B2b satellite slots",
    )
    parser.add_argument(
        "--has",
        action="store_true",
        help="also collect Galileo HAS blocks for a dual-service census",
    )
    parser.add_argument(
        "--alignment-window",
        type=float,
        default=60.0,
        help="seconds of preceding corrections shown beside each PPP navigation epoch",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    paths = [
        path
        for path in (
            args.replay,
            args.record,
            args.json,
            args.navigation,
            args.checks_csv,
        )
        if path is not None
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, output and reference paths must be distinct")
    debug_header(args, "b2b_correction_audit")
    navigation = (
        read_numeric_csv(args.navigation, ("slot", "iodn")) if args.navigation else ()
    )
    if any(
        row["slot"] != int(row["slot"]) or row["iodn"] != int(row["iodn"])
        for row in navigation
    ):
        raise ValueError("navigation slots and issues must be integers")
    if len({row["slot"] for row in navigation}) != len(navigation):
        raise ValueError("navigation reference slots must be unique")
    ordered: list[Record] = []
    captured = capture_logs(
        args,
        LOGS + (HAS_LOGS if args.has else ()) + (Log.PPPNAV,),
        arrival_order=ordered,
        on_progress=progress_printer("b2b_correction_audit") if args.debug else None,
    )
    has_records = tuple(
        record for log in HAS_LOGS for record in captured.get(log.value, ())
    )
    events = [
        event
        for record in ordered
        if record.name.startswith("PPPB2BINFO")
        for event in correction_events(record)
    ]
    has_checks = (
        audit_has(
            chronological(has_records),
            max_age=args.max_age,
            mask_max_age=args.mask_max_age,
        )
        if has_records
        else ()
    )
    checks = audit_corrections(
        events,
        max_age=args.max_age,
        mask_max_age=args.mask_max_age,
        navigation_issues={int(row["slot"]): int(row["iodn"]) for row in navigation}
        if navigation
        else None,
    )
    alignment = align_navigation(
        captured["PPPNAV"], checks, has_checks, window_seconds=args.alignment_window
    )
    observed = bool(checks or has_checks)
    if args.checks_csv is not None:
        args.checks_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.checks_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ("received_gps_seconds", "transmitter", "kind", "age_seconds", "flags")
            )
            writer.writerows(
                (
                    check.received,
                    check.transmitter,
                    check.kind,
                    check.age_seconds,
                    ";".join(check.flags),
                )
                for check in checks
            )
    print(
        f"B2b audit: {len(checks)} correction checks, "
        f"{len(has_checks)} HAS checks, observed={observed}",
        file=sys.stderr,
    )
    write_json(
        {
            "status": "ok" if observed else "no_corrections",
            "reference_sha256": file_sha256(args.navigation)
            if args.navigation
            else None,
            "ground_truth": str(args.navigation)
            if navigation
            else "no independent navigation-issue reference supplied",
            "time_model": (
                "Message epoch is BeiDou seconds of day, with GPST = BDT + 14s. "
                "Nearest-day resolution requires latency under 12h."
            ),
            "limitation": (
                "Native correction integers are not applied, and mask-based "
                "clock satellite mapping remains unverified. Stream coherence "
                "does not establish positioning accuracy"
            ),
            "counts": dict(Counter(check.kind for check in checks)),
            "services": [asdict(audit) for audit in service_census(checks, has_checks)],
            "has_counts": dict(Counter(str(row.get("source")) for row in has_checks)),
            "checks": [asdict(check) for check in checks],
            "has_checks": list(has_checks),
            "ppp_navigation_alignment": [asdict(item) for item in alignment],
            "next_step": None
            if observed
            else (
                "use PPP-capable firmware and a location or recording "
                "with PPP-B2b or E6-HAS reception"
            ),
        },
        args.json,
    )
    return 0 if observed else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
