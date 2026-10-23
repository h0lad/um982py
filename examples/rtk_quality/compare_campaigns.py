"""Compare receiver solution quality across labelled field sessions."""

import argparse
import csv
import itertools
import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from um982py.field_data import file_sha256, nearest_epoch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign",
        nargs=2,
        action="append",
        required=True,
        metavar=("NAME", "QUALITY_JSON"),
        help="named report from examples.rtk_quality; repeat for more sessions",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="CSV with start_gps_seconds,end_gps_seconds,environment",
    )
    parser.add_argument(
        "--truth-error", type=Path, help="independent CSV with gps_seconds,error_m"
    )
    parser.add_argument("--cn0", type=Path, help="CSV with gps_seconds,cn0_dbhz")
    parser.add_argument("--truth-window-s", type=float, default=0.5)
    parser.add_argument("--max-gap-s", type=float, default=2)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.truth_window_s)
        or args.truth_window_s < 0
        or not math.isfinite(args.max_gap_s)
        or args.max_gap_s <= 0
    ):
        parser.error("matching window must be non-negative and gap must be positive")
    names = [item[0] for item in args.campaign]
    if any(not name.strip() for name in names) or len(names) != len(set(names)):
        parser.error("campaign names must be non-empty and unique")
    inputs = [Path(item[1]) for item in args.campaign] + [
        p for p in (args.labels, args.truth_error, args.cn0) if p is not None
    ]
    if args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must differ from every input")
    labels: list[tuple[float, float, str]] = []
    if args.labels:
        with args.labels.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                start, end, label = (
                    float(row["start_gps_seconds"]),
                    float(row["end_gps_seconds"]),
                    row["environment"].strip(),
                )
                if (
                    not math.isfinite(start)
                    or not math.isfinite(end)
                    or end <= start
                    or not label
                ):
                    raise ValueError(
                        "labels require finite increasing bounds and a name"
                    )
                labels.append((start, end, label))
        labels.sort()
        if any(b[0] < a[1] for a, b in itertools.pairwise(labels)):
            raise ValueError("environment intervals must not overlap")
    truth: list[tuple[float, float]] = []
    if args.truth_error:
        with args.truth_error.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                epoch, error = float(row["gps_seconds"]), float(row["error_m"])
                if not math.isfinite(epoch) or not math.isfinite(error) or error < 0:
                    raise ValueError(
                        "truth error epochs and non-negative errors must be finite"
                    )
                truth.append((epoch, error))
    truth.sort()
    truth_times = [sample[0] for sample in truth]
    cn0: list[tuple[float, float]] = []
    if args.cn0:
        with args.cn0.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                epoch, value = float(row["gps_seconds"]), float(row["cn0_dbhz"])
                if not math.isfinite(epoch) or not math.isfinite(value) or value <= 0:
                    raise ValueError(
                        "C/N0 values and epochs must be finite and positive"
                    )
                cn0.append((epoch, value))
    cn0.sort()
    cn0_times = [sample[0] for sample in cn0]
    reports = []
    for name, file in args.campaign:
        payload = json.loads(Path(file).read_text(encoding="utf-8"))
        rows = payload["epochs"]
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        gaps: list[dict[str, float]] = []
        outages: list[dict[str, object]] = []
        previous = None
        previous_environment = None
        unavailable_start: float | None = None
        unavailable_environment: str | None = None
        for row in rows:
            epoch = float(row["epoch"])
            if not math.isfinite(epoch) or (previous is not None and epoch <= previous):
                raise ValueError(
                    "quality epochs must be finite and strictly increasing"
                )
            environment = next(
                (label for start, end, label in labels if start <= epoch < end),
                "unlabelled",
            )
            gap = previous is not None and epoch - previous > args.max_gap_s
            if gap and previous is not None:
                gaps.append({"start_gps_seconds": previous, "end_gps_seconds": epoch})
            if unavailable_start is not None and (
                gap or environment != previous_environment
            ):
                outages.append(
                    {
                        "environment": unavailable_environment,
                        "first_unavailable_gps_seconds": unavailable_start,
                        "last_observed_gps_seconds": previous,
                        "recovered_gps_seconds": None,
                        "censored": True,
                    }
                )
                unavailable_start = None
            if row["available"] is False and unavailable_start is None:
                unavailable_start = epoch
                unavailable_environment = environment
            elif row["available"] is True and unavailable_start is not None:
                outages.append(
                    {
                        "environment": unavailable_environment,
                        "first_unavailable_gps_seconds": unavailable_start,
                        "last_observed_gps_seconds": previous,
                        "recovered_gps_seconds": epoch,
                        "observed_interval_s": epoch - unavailable_start,
                        "censored": False,
                    }
                )
                unavailable_start = None
            previous, previous_environment = epoch, environment
            groups[environment].append(row)
        if unavailable_start is not None:
            outages.append(
                {
                    "environment": unavailable_environment,
                    "first_unavailable_gps_seconds": unavailable_start,
                    "last_observed_gps_seconds": previous,
                    "recovered_gps_seconds": None,
                    "censored": True,
                }
            )
        summaries = []
        for environment, samples in sorted(groups.items()):
            classes = Counter(str(row["fix_class"]) for row in samples)
            errors = []
            signals = []
            for sample in samples:
                epoch = float(sample["epoch"])
                nearest = nearest_epoch(truth, truth_times, epoch)
                if (
                    nearest is not None
                    and abs(nearest[0] - epoch) <= args.truth_window_s
                    and sample["available"] is True
                ):
                    errors.append(nearest[1])
                signal = nearest_epoch(cn0, cn0_times, epoch)
                if signal is not None and abs(signal[0] - epoch) <= args.truth_window_s:
                    signals.append(signal[1])
            ages = [
                float(row["differential_age"])
                for row in samples
                if row["available"]
                and row["fix_class"] in ("fixed", "float")
                and row["differential_age"] is not None
                and math.isfinite(float(row["differential_age"]))
                and float(row["differential_age"]) >= 0
            ]
            summaries.append(
                {
                    "environment": environment,
                    "epochs": len(samples),
                    "computed_epochs": sum(row["available"] is True for row in samples),
                    "computed_fraction": sum(
                        row["available"] is True for row in samples
                    )
                    / len(samples),
                    "fresh_fixed_epochs": sum(
                        row["fresh_fixed"] is True for row in samples
                    ),
                    "fix_classes": dict(classes),
                    "mean_reported_correction_age_s": math.fsum(ages) / len(ages)
                    if ages
                    else None,
                    "correction_age_samples": len(ages),
                    "matched_truth_samples": len(errors),
                    "matched_cn0_samples": len(signals),
                    "mean_cn0_dbhz": math.fsum(signals) / len(signals)
                    if signals
                    else None,
                    "rms_position_error_m": math.sqrt(
                        math.fsum(x * x for x in errors) / len(errors)
                    )
                    if errors
                    else None,
                }
            )
        reports.append(
            {
                "name": name,
                "source": file,
                "environments": summaries,
                "total_epochs": len(rows),
                "gaps_over_limit": gaps,
                "observed_unavailability_intervals": outages,
            }
        )
    result = {
        "campaigns": reports,
        "inputs": [{"path": str(p), "sha256": file_sha256(p)} for p in inputs],
        "truth_match_window_s": args.truth_window_s,
        "max_gap_s": args.max_gap_s,
        "limitations": (
            "Fractions are based on observed epochs, not elapsed time. Labels "
            "and truth must be established independently on the same GPS time "
            "scale, frame and antenna point. Nearest truth samples can be "
            "reused. C/N0 samples are supplied independently and may be reused. "
            "Correction-age summaries include only available RTK float and fixed "
            "solutions. "
            "Unavailable intervals begin at the first observed unavailable "
            "epoch, so their true onset is unknown. Gaps and label changes "
            "censor a pending interval. Conditions and capture intervals can "
            "differ between sessions, so this is not a controlled comparison."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if any(r["total_epochs"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
