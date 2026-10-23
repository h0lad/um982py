"""Runs the UERE budget example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from examples.uere_budget import (
    UereEstimate,
    agreement_ratio,
    estimate_epoch,
    median_uere,
    pseudorange_uere,
)
from um982py.capture import capture_records, record_epoch
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
from um982py.stats import percentile


def _estimate_payload(estimate: UereEstimate) -> dict[str, object]:
    """Serialise one epoch estimate."""
    return {
        "epoch": estimate.epoch,
        "horizontal_sigma": estimate.horizontal_sigma,
        "vertical_sigma": estimate.vertical_sigma,
        "hdop": estimate.hdop,
        "vdop": estimate.vdop,
        "horizontal_uere": estimate.horizontal_uere,
        "vertical_uere": estimate.vertical_uere,
    }


def _payload(
    positions: Sequence[Record],
    dilutions: Sequence[Record],
    ranges: Sequence[Record],
) -> dict[str, object]:
    """Build the UERE budget from the decoded logs."""
    by_epoch = {record_epoch(record): record for record in dilutions}
    paired = [
        (position, by_epoch[record_epoch(position)])
        for position in positions
        if record_epoch(position) in by_epoch
    ]
    estimates = [
        estimate_epoch(record_epoch(position), position, dilution)
        for position, dilution in paired
    ]
    paired_epochs = {record_epoch(position) for position, _ in paired}
    matched_ranges = [
        record for record in ranges if record_epoch(record) in paired_epochs
    ]
    reference_ranges = matched_ranges or ranges[:1]
    pseudorange = (
        percentile([pseudorange_uere(record) for record in reference_ranges], 0.5)
        if reference_ranges
        else None
    )
    if not estimates:
        return {
            "epochs": 0,
            "estimates": [],
            "uere": None,
            "pseudorange_uere": pseudorange,
            "agreement": None,
        }
    horizontal, vertical = median_uere(estimates)
    return {
        "epochs": len(estimates),
        "estimates": [_estimate_payload(estimate) for estimate in estimates],
        "uere": {"horizontal": horizontal, "vertical": vertical},
        "pseudorange_uere": pseudorange,
        "pseudorange_comparison_epochs": len(matched_ranges),
        "agreement": None
        if pseudorange is None or not matched_ranges
        else {
            "horizontal": agreement_ratio(horizontal, pseudorange),
            "vertical": agreement_ratio(vertical, pseudorange),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Estimate UERE per epoch and cross-check it against the pseudorange sigma."""
    parser = ExampleParser(
        prog="python -m examples.uere_budget",
        description="Invert sigma_position = DOP * sigma_UERE on captured epochs.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
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
    debug_header(args, "uere_budget")
    captured = capture_records(
        args,
        [FirmwareLog.BESTPOS, FirmwareLog.PSRDOP, FirmwareLog.RANGE],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("uere_budget") if args.debug else None,
    )
    payload = _payload(captured["BESTPOS"], captured["PSRDOP"], captured["RANGE"])
    if not payload["epochs"] and payload["pseudorange_uere"] is None:
        write_json({"status": "insufficient_data", "payload": payload}, args.json)
        return 1
    uere = payload["uere"]
    if isinstance(uere, dict):
        print(
            f"UERE: horizontal {uere['horizontal']:.3f} m, "
            f"vertical {uere['vertical']:.3f} m over {payload['epochs']} epochs",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
