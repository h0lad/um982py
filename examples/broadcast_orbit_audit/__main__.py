# Compare GPS broadcast orbits with an SP3 product.

import csv
import hashlib
import importlib
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

from examples._console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_logs
from examples.broadcast_orbit_audit import OrbitDifference, compare_state, sisre_summary
from um982py.commands import Log
from um982py.experimental.gps_motion import choose_ephemeris
from um982py.experimental.orbit import KeplerElements, orbit_state
from um982py.gnss import SPEED_OF_LIGHT, WEEK_SECONDS
from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.precise import parse_sp3
from um982py.stats import rms

_PROVENANCE_FIELDS = (
    "ephemeris_toe_gps_seconds",
    "ephemeris_received_gps_seconds",
    "predicted_reference_orbit",
    "predicted_reference_clock",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Compare healthy GPS broadcast states at exact precise-product epochs."""
    parser = experiment_parser(
        "broadcast_orbit_audit",
        "Independent GPS orbit and clock product comparison",
        output_rate=False,
    )
    parser.add_argument(
        "--sp3",
        type=Path,
        required=True,
        help="SP3-c/d precise product explicitly in GPS time",
    )
    parser.add_argument(
        "--include-predicted",
        action="store_true",
        help="include predicted ultra-rapid orbit epochs",
    )
    parser.add_argument(
        "--start-gps-seconds", type=float, help="first comparison epoch"
    )
    parser.add_argument("--end-gps-seconds", type=float, help="last comparison epoch")
    parser.add_argument(
        "--predicted-from-gps-seconds",
        type=float,
        help="documented first prediction epoch for a product without point flags",
    )
    parser.add_argument(
        "--causal",
        action="store_true",
        help="use only broadcast ephemerides received by each comparison epoch",
    )
    parser.add_argument(
        "--differences-csv", type=Path, help="export per-epoch RAC differences"
    )
    parser.add_argument("--plot", type=Path, help="save RAC plot (requires matplotlib)")
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    start, end = args.start_gps_seconds, args.end_gps_seconds
    predicted_from = args.predicted_from_gps_seconds
    if any(
        value is not None and not math.isfinite(value)
        for value in (start, end, predicted_from)
    ) or (start is not None and end is not None and start > end):
        parser.error("comparison bounds must be finite and in chronological order")
    paths = [
        path
        for path in (
            args.sp3,
            args.replay,
            args.record,
            args.json,
            args.differences_csv,
            args.plot,
        )
        if path is not None
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, output and report paths must be distinct")
    debug_header(args, "broadcast_orbit_audit")
    sp3 = args.sp3.read_bytes()
    product = parse_sp3(sp3.decode("ascii"))
    data = capture_logs(
        args,
        [Log.GPSEPH],
        on_progress=progress_printer("broadcast_orbit_audit") if args.debug else None,
    )
    rows: list[OrbitDifference] = []
    metadata: list[dict[str, float | bool]] = []
    ephemerides: dict[int, list[tuple[float, Record]]] = defaultdict(list)
    for record in data["GPSEPH"]:
        ephemerides[record.integer("prn")].append((gps_epoch(record), record))
    skipped: dict[str, int] = defaultdict(int)
    for point in product.points:
        if not point.satellite.startswith("G"):
            continue
        if (start is not None and point.epoch < start) or (
            end is not None and point.epoch > end
        ):
            skipped["outside_comparison_window"] += 1
            continue
        predicted_by_epoch = (
            predicted_from is not None and point.epoch >= predicted_from
        )
        predicted_orbit = point.predicted_orbit or predicted_by_epoch
        predicted_clock = point.predicted_clock or predicted_by_epoch
        if predicted_orbit and not args.include_predicted:
            skipped["predicted_orbit"] += 1
            continue
        try:
            prn = int(point.satellite[1:])
            candidates = [
                record
                for received, record in ephemerides[prn]
                if not args.causal or received <= point.epoch
            ]
            record = choose_ephemeris(candidates, prn, point.epoch)
        except ValueError:
            skipped["no_healthy_matching_ephemeris"] += 1
            continue
        elements = KeplerElements.from_record(record)
        toe = record.integer("week") * WEEK_SECONDS + elements.toe
        dt = point.epoch - toe
        metadata.append(
            {
                "ephemeris_toe_gps_seconds": toe,
                "ephemeris_received_gps_seconds": gps_epoch(record),
                "predicted_reference_orbit": predicted_orbit,
                "predicted_reference_clock": predicted_clock,
            }
        )
        state = orbit_state(elements, dt)
        before, after = orbit_state(elements, dt - 0.5), orbit_state(elements, dt + 0.5)
        rows.append(
            compare_state(
                point.satellite,
                point.epoch,
                (state.x, state.y, state.z),
                point.position,
                (after.x - before.x, after.y - before.y, after.z - before.z),
                broadcast_clock=state.clock_bias + elements.tgd,
                reference_clock=None
                if predicted_clock and not args.include_predicted
                else point.clock_seconds,
            )
        )
    clocks: dict[float, list[float]] = defaultdict(list)
    for row in rows:
        if row.clock_difference_seconds is not None:
            clocks[row.epoch].append(row.clock_difference_seconds)
    aligned = [
        replace(
            row,
            clock_difference_seconds=row.clock_difference_seconds
            - median(clocks[row.epoch]),
        )
        for row in rows
        if row.clock_difference_seconds is not None and len(clocks[row.epoch]) >= 4
    ]
    if args.differences_csv is not None:
        with args.differences_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "satellite",
                    "gps_seconds",
                    "radial_m",
                    "along_m",
                    "cross_m",
                    "norm_m",
                    "clock_difference_seconds",
                    *_PROVENANCE_FIELDS,
                )
            )
            writer.writerows(
                (
                    r.satellite,
                    r.epoch,
                    r.radial_m,
                    r.along_m,
                    r.cross_m,
                    r.norm_m,
                    r.clock_difference_seconds,
                    *(details[name] for name in _PROVENANCE_FIELDS),
                )
                for r, details in zip(rows, metadata, strict=True)
            )
    if args.plot is not None:
        try:
            plt = importlib.import_module("matplotlib.pyplot")
        except ImportError as error:
            raise ValueError("--plot requires matplotlib") from error
        figure, axes = plt.subplots(3, 1, sharex=True, figsize=(10, 7))
        for satellite in sorted({row.satellite for row in rows}):
            points = [row for row in rows if row.satellite == satellite]
            for axis, key in zip(axes, ("radial_m", "along_m", "cross_m"), strict=True):
                axis.plot(
                    [row.epoch for row in points],
                    [getattr(row, key) for row in points],
                    label=satellite,
                )
                axis.set_ylabel(key.replace("_", " "))
        axes[-1].set_xlabel("GPS seconds since 1980-01-06")
        if rows:
            axes[0].legend(ncol=4, fontsize="small")
        figure.tight_layout()
        figure.savefig(args.plot)
        plt.close(figure)
    write_json(
        {
            "status": "ok" if rows else "insufficient_overlap",
            "ground_truth": str(args.sp3),
            "reference_sha256": hashlib.sha256(sp3).hexdigest(),
            "reference_frame": product.coordinate_system,
            "reference_agency": product.agency,
            "comparison_window": {
                "requested_start_gps_seconds": start,
                "requested_end_gps_seconds": end,
                "first_compared_gps_seconds": min(
                    (row.epoch for row in rows), default=None
                ),
                "last_compared_gps_seconds": max(
                    (row.epoch for row in rows), default=None
                ),
                "causal": args.causal,
                "include_predicted": args.include_predicted,
                "predicted_from_gps_seconds": predicted_from,
            },
            "limitation": (
                "product differences include reference-frame and antenna "
                "reference-point differences, while clocks use broadcast "
                "polynomial plus relativity without TGD, and raw clock "
                "offsets retain datum and bias differences"
            ),
            "position_3d_rms_m": rms([row.norm_m for row in rows]) if rows else None,
            "differences": [
                {
                    **asdict(row),
                    **details,
                    "common_clock_aligned_m": (
                        row.clock_difference_seconds - median(clocks[row.epoch])
                    )
                    * SPEED_OF_LIGHT
                    if row.clock_difference_seconds is not None
                    and len(clocks[row.epoch]) >= 4
                    else None,
                }
                for row, details in zip(rows, metadata, strict=True)
            ],
            "sisre": asdict(sisre_summary(aligned)),
            "skipped": dict(skipped),
            "next_step": None
            if rows
            else (
                "provide a GPSEPH capture and an SP3 product covering the"
                " same GPS week and epochs"
            ),
        },
        args.json,
    )
    print(
        f"Broadcast orbit: {len(rows)} comparisons; "
        f"3D RMS "
        f"{rms([row.norm_m for row in rows]):.3f} m"
        if rows
        else "Broadcast orbit: no overlapping comparisons",
        file=sys.stderr,
    )
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
