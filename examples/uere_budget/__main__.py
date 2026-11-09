"""Estimate user range error from position uncertainty and DOP."""

from __future__ import annotations

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
from examples.uere_budget import (
    UereEstimate,
    agreement_ratio,
    estimate_epoch,
    median_uere,
    pseudorange_uere,
)
from um982py.capture import record_epoch
from um982py.commands import Log
from um982py.messages import Record
from um982py.stats import percentile


def _estimate_payload(estimate: UereEstimate) -> dict[str, object]:
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
    *,
    assume_matched_geometry: bool = False,
) -> dict[str, object]:
    """Build the UERE budget from the decoded logs."""
    by_epoch = {record_epoch(record): record for record in dilutions}
    paired = [
        (position, by_epoch[record_epoch(position)])
        for position in positions
        if record_epoch(position) in by_epoch
        and position.get("sol_status", position.get("p_sol_status"))
        in (0, "SOL_COMPUTED")
        and position.get("pos_type") in (16, "SINGLE")
        and assume_matched_geometry
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
            "median_reported_pseudorange_sigma_m": pseudorange,
            "diagnostic_ratio_to_pseudorange_sigma": None,
            "limitation": "Satellite geometry match is unverified.",
        }
    horizontal, vertical = median_uere(estimates)
    return {
        "epochs": len(estimates),
        "estimates": [_estimate_payload(estimate) for estimate in estimates],
        "uere": {"horizontal": horizontal, "vertical": vertical},
        "median_reported_pseudorange_sigma_m": pseudorange,
        "limitation": (
            "Assumes matching unweighted satellite geometry and independent equal "
            "range errors. RANGE sigmas are receiver diagnostics, not total UERE."
        ),
        "pseudorange_comparison_epochs": len(matched_ranges),
        "diagnostic_ratio_to_pseudorange_sigma": None
        if pseudorange is None
        or pseudorange <= 0
        or not matched_ranges
        or horizontal <= 0
        or vertical <= 0
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
    parser.add_argument(
        "--assume-matched-geometry",
        action="store_true",
        help="assert that PSRPOS and PSRDOP use the same unweighted satellites",
    )
    args = parser.parse_args(argv)
    debug_header(args, "uere_budget")
    captured = capture_records(
        args,
        [Log.PSRPOS, Log.PSRDOP, Log.RANGE],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("uere_budget") if args.debug else None,
    )
    payload = _payload(
        captured["PSRPOS"],
        captured["PSRDOP"],
        captured["RANGE"],
        assume_matched_geometry=args.assume_matched_geometry,
    )
    if not payload["epochs"]:
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
