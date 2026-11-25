# Estimate heading and pitch with a known baseline-length constraint.

import math
import sys
from collections.abc import Sequence

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.heading_baseline_constraint import (
    attitude_from_record,
    heading_residual,
)
from um982py.commands import Log
from um982py.measurement import gps_epoch
from um982py.messages import Record

LENGTH_Z_LIMIT = 3.0


def _payload(
    records: Sequence[Record],
    heading_records: Sequence[Record],
    baseline_length_m: float,
) -> dict[str, object]:
    """Match baselines to heading epochs and compute constrained attitudes."""
    # Index receiver heading reports by GPS seconds for matching.
    heading_by_epoch: dict[float, Record] = {}
    for heading in heading_records:
        epoch = gps_epoch(heading)
        if epoch is not None:
            heading_by_epoch[epoch] = heading

    results: list[dict[str, object]] = []
    residuals: list[float] = []
    pitch_diffs: list[float] = []
    length_errors: list[float] = []
    length_scores: list[float] = []

    for record in records:
        epoch = gps_epoch(record)
        try:
            attitude = attitude_from_record(record, baseline_length_m)
        except ValueError:
            continue

        heading_rec = heading_by_epoch.get(epoch) if epoch is not None else None
        receiver_heading: float | None = None
        receiver_pitch: float | None = None
        residual: float | None = None
        pitch_diff: float | None = None
        if heading_rec is not None:
            receiver_heading = heading_rec.real("heading")
            receiver_pitch = heading_rec.real("pitch")
            if math.isfinite(receiver_heading) and math.isfinite(receiver_pitch):
                residual = heading_residual(receiver_heading, attitude.heading)
                pitch_diff = receiver_pitch - attitude.pitch

        results.append(
            {
                "epoch": epoch,
                "constrained_heading": attitude.heading,
                "constrained_pitch": attitude.pitch,
                "receiver_heading": receiver_heading,
                "receiver_pitch": receiver_pitch,
                "heading_residual_deg": residual,
                "pitch_residual_deg": pitch_diff,
                "constrained_length": attitude.baseline_length,
                "unconstrained_length": attitude.unconstrained_length,
                "unconstrained_length_error": (
                    attitude.unconstrained_length - baseline_length_m
                ),
                "unconstrained_length_sigma": attitude.length_sigma,
                "length_z_score": attitude.length_z_score,
                "position_type": record.get("pos_type"),
            }
        )
        if attitude.length_z_score is not None:
            length_scores.append(attitude.length_z_score)
        if residual is not None:
            residuals.append(residual)
        if pitch_diff is not None:
            pitch_diffs.append(pitch_diff)
        length_errors.append(attitude.unconstrained_length - baseline_length_m)

    def _rms(values: Sequence[float]) -> float | None:
        if not values:
            return None
        return math.sqrt(sum(v * v for v in values) / len(values))

    def _std(values: Sequence[float]) -> float | None:
        if len(values) < 2:
            return None
        mean = sum(values) / len(values)
        return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))

    return {
        "baseline_length_m": baseline_length_m,
        "matched_epochs": len(results),
        "attitudes": results,
        "statistics": {
            "heading_residual_rms_deg": _rms(residuals),
            "heading_residual_std_deg": _std(residuals),
            "heading_residual_mean_deg": (
                sum(residuals) / len(residuals) if residuals else None
            ),
            "pitch_residual_rms_deg": _rms(pitch_diffs),
            "pitch_residual_std_deg": _std(pitch_diffs),
            "unconstrained_length_error_mean_m": (
                sum(length_errors) / len(length_errors) if length_errors else None
            ),
            "unconstrained_length_error_std_m": _std(length_errors),
            "length_test_epochs": len(length_scores),
            "length_inconsistent_epochs": sum(
                abs(score) > LENGTH_Z_LIMIT for score in length_scores
            ),
        },
        "length_test": (
            f"|raw length - supplied length| > {LENGTH_Z_LIMIT:g} sigma marks a "
            "receiver baseline that contradicts the physical separation; its "
            "heading and pitch are then unreliable."
        ),
        "limitation": (
            "Equal-weight rescaling preserves the full baseline direction and "
            "cannot improve its heading or pitch. Residuals are relative to the "
            "receiver's own UNIHEADING output, not an independent truth."
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.heading_baseline_constraint",
        description=(
            "Estimate heading and pitch from a BSLNENUHD baseline while "
            "constraining its length to the measured antenna separation."
        ),
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--baseline-length",
        type=float,
        required=True,
        help="measured physical antenna separation in metres",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="live collection time in seconds",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="capture interval in seconds, and logs output remains ONCHANGED",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    records = capture_records(
        args,
        [Log.BSLNENUHD, Log.UNIHEADING],
        duration=args.duration,
        interval=args.interval,
    )
    baselines = records.get("BSLNENUHD", ())
    if not baselines:
        # Antenna routing may have renamed the log.
        for name, values in records.items():
            if "BSLN" in name and values:
                baselines = values
                break
    if not baselines:
        parser.error("no baseline log captured; dual-antenna solution required")

    headings = records.get("UNIHEADING", ())
    payload = _payload(baselines, headings, args.baseline_length)
    stats = payload["statistics"]
    heading_rms = stats["heading_residual_rms_deg"] if isinstance(stats, dict) else None
    counts = stats if isinstance(stats, dict) else {}
    rms_text = f"{heading_rms:.3f} deg" if isinstance(heading_rms, float) else "N/A"
    print(
        f"Matched {payload['matched_epochs']} epochs; "
        f"heading residual RMS = {rms_text}; "
        f"{counts.get('length_inconsistent_epochs')} of "
        f"{counts.get('length_test_epochs')} "
        f"baselines contradict the {payload['baseline_length_m']:g} m length",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
