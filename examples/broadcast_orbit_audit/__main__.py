"""Compares broadcast and SP3 states from the command line."""

import csv
import importlib
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

from examples.broadcast_orbit_audit import (
    OrbitDifference,
    compare_state,
    sisre_summary,
)
from examples.ephemeris_orbit import KeplerElements, orbit_state
from um982py import parse_sp3
from um982py.capture import capture_logs
from um982py.commands import Log
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.experimental.gps_motion import choose_ephemeris
from um982py.stats import rms


def main(argv: Sequence[str] | None = None) -> int:
    """Compare healthy GPS broadcast states at exact precise-product epochs."""
    parser = experiment_parser(
        "broadcast_orbit_audit", "Independent GPS orbit and clock product comparison"
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
        "--differences-csv", type=Path, help="export per-epoch RAC differences"
    )
    parser.add_argument("--plot", type=Path, help="save RAC plot (requires matplotlib)")
    add_debug_argument(parser)
    args = parser.parse_args(argv)
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
    product = parse_sp3(args.sp3.read_text(encoding="ascii"))
    data = capture_logs(
        args,
        [Log.GPSEPH],
        on_progress=progress_printer("broadcast_orbit_audit") if args.debug else None,
    )
    rows: list[OrbitDifference] = []
    skipped: dict[str, int] = defaultdict(int)
    for point in product.points:
        if not point.satellite.startswith("G"):
            continue
        if point.predicted_orbit and not args.include_predicted:
            skipped["predicted_orbit"] += 1
            continue
        try:
            record = choose_ephemeris(
                data["GPSEPH"], int(point.satellite[1:]), point.epoch
            )
        except ValueError:
            skipped["no_healthy_matching_ephemeris"] += 1
            continue
        elements = KeplerElements.from_record(record)
        dt = point.epoch - (record.integer("week") * 604800 + elements.toe)
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
                if point.predicted_clock and not args.include_predicted
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
                )
                for r in rows
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
            "reference_frame": product.coordinate_system,
            "reference_agency": product.agency,
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
                    "common_clock_aligned_m": (
                        row.clock_difference_seconds - median(clocks[row.epoch])
                    )
                    * 299792458.0
                    if row.clock_difference_seconds is not None
                    and len(clocks[row.epoch]) >= 4
                    else None,
                }
                for row in rows
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
