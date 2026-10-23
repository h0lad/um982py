"""Runs repeat-day site multipath experiments from the command line."""

import sys
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.sidereal_multipath import SkyResidual, evaluate_repeatability
from um982py.antenna import antenna_log
from um982py.capture import capture_logs, load_records, record_epoch
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.measurement import RangeSample, sample_series
from um982py.messages import Record
from um982py.stats import detrend, is_continuous


def sky_residuals(
    ranges: Sequence[Record], visibility: Sequence[Record]
) -> tuple[SkyResidual, ...]:
    """Remove linear arc drift and join GPS visibility within twenty milliseconds."""
    skies: dict[float, dict[int, tuple[float, float]]] = {}
    for record in visibility:
        if record.get("constellation") not in (0, "GPS"):
            continue
        sky = skies.setdefault(record_epoch(record), {})
        for satellite in record.records("satellites"):
            sky[satellite.integer("prn")] = (
                satellite.real("azimuth"),
                satellite.real("elevation"),
            )
    times = sorted(skies)
    result = []
    for samples in sample_series(ranges).values():
        arcs: list[list[RangeSample]] = []
        for sample in samples:
            if not arcs or not is_continuous(arcs[-1][-1], sample):
                arcs.append([])
            arcs[-1].append(sample)
        for arc in arcs:
            if len(arc) < 3:
                continue
            residuals = detrend(
                [item.epoch - arc[0].epoch for item in arc],
                [item.code_m - item.phase_m for item in arc],
            )
            for sample, residual in zip(arc, residuals, strict=True):
                index = bisect_left(times, sample.epoch)
                nearby = times[max(0, index - 1) : index + 1]
                if not nearby:
                    continue
                epoch = min(nearby, key=lambda time: abs(time - sample.epoch))
                if (
                    abs(epoch - sample.epoch) > 0.02
                    or sample.key.prn not in skies[epoch]
                ):
                    continue
                azimuth, elevation = skies[epoch][sample.key.prn]
                result.append(
                    SkyResidual(sample.key, sample.epoch, azimuth, elevation, residual)
                )
    return tuple(result)


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate a frozen site map using a separate later capture."""
    parser = experiment_parser(
        "sidereal_multipath", "Held-out repeat-track multipath fingerprint"
    )
    parser.add_argument(
        "--training",
        type=Path,
        required=True,
        help="earlier RANGE plus SATVIS2 capture at the same stationary site",
    )
    parser.add_argument("--cell-degrees", type=float, default=5.0)
    parser.add_argument("--minimum-cell-samples", type=int, default=3)
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "sidereal_multipath")
    if args.cell_degrees > 30:
        parser.error("--cell-degrees must not exceed 30")
    data = capture_logs(
        args,
        [FirmwareLog.RANGE, FirmwareLog.SATVIS2],
        on_progress=progress_printer("sidereal_multipath") if args.debug else None,
    )
    training = sky_residuals(
        load_records(args.training, antenna_log(FirmwareLog.RANGE, args.antenna)),
        load_records(args.training, FirmwareLog.SATVIS2),
    )
    validation = sky_residuals(data["RANGE"], data["SATVIS2"])
    score = evaluate_repeatability(
        training,
        validation,
        cell_degrees=args.cell_degrees,
        minimum_cell_samples=args.minimum_cell_samples,
    )
    write_json(
        {
            "status": "ok" if score.matched_samples else "insufficient_overlap",
            "ground_truth": (
                "held-out measurements, where repeatability is not absolute "
                "multipath truth"
            ),
            "model": (
                "GPS signal-specific sky cells, linear drift removed "
                "independently per continuous arc without assuming a fixed "
                "sidereal period"
            ),
            **asdict(score),
        },
        args.json,
    )
    print(
        f"Sidereal multipath: {score.matched_samples} matched samples",
        file=sys.stderr,
    )
    return 0 if score.matched_samples else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
