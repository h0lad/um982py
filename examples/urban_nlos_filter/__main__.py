# Flag likely NLOS satellites in an urban-canyon capture.
#
# Reads SATSINFO epochs and applies a receiver-only heuristic based on elevation
# and C/N0. Low scores mark satellites that are probably line-of-sight, and high
# scores flag candidates for exclusion or down-weighting.

import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.urban_nlos_filter import classify_record, evaluate_labelled
from um982py.commands import Log
from um982py.measurement import gps_epoch
from um982py.messages import Record


def _payload(
    records: Sequence[Record],
    low_threshold: float,
    high_threshold: float,
) -> dict[str, object]:
    epochs: list[dict[str, object]] = []
    total = 0
    nlos = 0
    unsure = 0
    los = 0
    mean_scores: list[float] = []

    for record in records:
        mean_score, candidates = classify_record(
            record, low_threshold=low_threshold, high_threshold=high_threshold
        )
        if mean_score is not None:
            mean_scores.append(mean_score)
        labels = {"LOS": 0, "unsure": 0, "NLOS": 0}
        for c in candidates:
            labels[c.label] += 1
        total += len(candidates)
        los += labels["LOS"]
        unsure += labels["unsure"]
        nlos += labels["NLOS"]
        epochs.append(
            {
                "epoch": gps_epoch(record),
                "mean_score": mean_score,
                "satellites": len(candidates),
                "counts": labels,
                "candidates": [
                    {
                        "prn": c.prn,
                        "constellation": c.constellation,
                        "elevation_deg": c.elevation_deg,
                        "azimuth_deg": c.azimuth_deg,
                        "snr_db_hz": c.snr_db_hz,
                        "score": c.score,
                        "label": c.label,
                    }
                    for c in candidates
                ],
            }
        )

    fraction_los = los / total if total else None
    fraction_unsure = unsure / total if total else None
    fraction_nlos = nlos / total if total else None

    return {
        "low_threshold": low_threshold,
        "high_threshold": high_threshold,
        "total_signals": total,
        "counts": {"LOS": los, "unsure": unsure, "NLOS": nlos},
        "fractions": {
            "LOS": fraction_los,
            "unsure": fraction_unsure,
            "NLOS": fraction_nlos,
        },
        "mean_score": (sum(mean_scores) / len(mean_scores) if mean_scores else None),
        "epochs": epochs,
        "limitation": (
            "This is a receiver-only heuristic.  Low elevation and low C/N0 can "
            "also indicate foliage, interference or poor sky view, not only "
            "NLOS.  Use the labels as candidates for further checks, not as "
            "ground truth."
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.urban_nlos_filter",
        description=(
            "Classify tracked satellites as LOS / unsure / NLOS from "
            "elevation and C/N0."
        ),
    )
    add_receiver_arguments(parser)
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
        help="capture interval in seconds",
    )
    parser.add_argument(
        "--low-threshold",
        type=float,
        default=0.45,
        help="score above which a satellite is marked unsure",
    )
    parser.add_argument(
        "--high-threshold",
        type=float,
        default=0.75,
        help="score above which a satellite is marked NLOS",
    )
    parser.add_argument(
        "--labels-csv",
        type=Path,
        help="held-out independent labels: elevation_deg,cn0_db_hz,truth",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    records = capture_records(
        args,
        [Log.SATSINFO],
        duration=args.duration,
        interval=args.interval,
    )["SATSINFO"]
    if not records:
        parser.error("no SATSINFO records captured")
    payload = _payload(records, args.low_threshold, args.high_threshold)
    if args.labels_csv is not None:
        with args.labels_csv.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        labelled = [
            (float(row["elevation_deg"]), float(row["cn0_db_hz"]), row["truth"].upper())
            for row in rows
        ]
        payload["held_out_label_evaluation"] = evaluate_labelled(
            labelled, args.low_threshold, args.high_threshold
        )
    counts = payload["counts"]
    if isinstance(counts, dict):
        print(
            f"Analysed {len(records)} epochs, {payload['total_signals']} signals: "
            f"LOS={counts['LOS']}, "
            f"unsure={counts['unsure']}, "
            f"NLOS={counts['NLOS']}",
            file=sys.stderr,
        )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
