# Show how far a GPS position moves without the relativistic clock term.

import sys
from collections.abc import Sequence
from dataclasses import asdict
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
from examples.relativistic_clock import (
    orbit_term,
    position_shift,
    without_relativity,
)
from examples.wls_position import MINIMUM_SATELLITES, solve_position
from examples.wls_position.measurements import (
    gps_l1_measurements,
    select_gps_ephemerides,
)
from um982py.commands import Log
from um982py.gnss import SPEED_OF_LIGHT, WEEK_SECONDS
from um982py.measurement import gps_epoch

_EPHEMERIS_LOGS = (Log.GPSEPH, Log.GALEPH, Log.BDSEPH)


def main(argv: Sequence[str] | None = None) -> int:
    """Solve each RANGE epoch with and without the eccentricity term."""
    parser = experiment_parser(
        "relativistic_clock",
        "Relativistic satellite clock term and its position effect",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "relativistic_clock")
    data = capture_logs(
        args,
        [Log.RANGE, *_EPHEMERIS_LOGS],
        on_progress=progress_printer("relativistic_clock") if args.debug else None,
    )
    terms = {
        (term.system, term.prn): term
        for log in _EPHEMERIS_LOGS
        for term in map(orbit_term, data[log.value])
    }
    shifts = []
    satellites: dict[int, list[float]] = {}
    for record in data["RANGE"]:
        epoch = gps_epoch(record)
        ephemerides = select_gps_ephemerides(data["GPSEPH"], epoch, ranges=record)
        measurements = gps_l1_measurements(record, ephemerides, epoch % WEEK_SECONDS)
        if len(measurements) < MINIMUM_SATELLITES:
            continue
        start = (0.0, 0.0, 0.0, 0.0)
        full = solve_position(measurements, start)
        reduced = solve_position(without_relativity(measurements), start)
        if not full.converged or not reduced.converged:
            continue
        shifts.append(position_shift(full, reduced))
        for item in measurements:
            satellites.setdefault(item.prn, []).append(item.relativity)
    largest = sorted(terms.values(), key=lambda term: -term.amplitude_ns)
    summary = (
        {
            "epochs": len(shifts),
            "median_horizontal_m": median(shift.horizontal_m for shift in shifts),
            "median_up_m": median(shift.up_m for shift in shifts),
            "median_clock_m": median(shift.clock_m for shift in shifts),
            "max_three_d_m": max(shift.three_d_m for shift in shifts),
        }
        if shifts
        else None
    )
    write_json(
        {
            "status": "ok" if shifts else "insufficient_data",
            "position_shift_without_relativity": summary,
            "gps_terms_used": {
                f"G{prn:02d}": {
                    "mean_ns": sum(values) / len(values) * 1e9,
                    "mean_m": sum(values) / len(values) * SPEED_OF_LIGHT,
                }
                for prn, values in sorted(satellites.items())
            },
            "orbit_amplitudes": [asdict(term) for term in largest],
            "epoch_shifts": [
                {**asdict(shift), "horizontal_m": shift.horizontal_m}
                for shift in shifts
            ],
        },
        args.json,
    )
    if summary is not None:
        print(
            f"Relativity: without the term a GPS position moves "
            f"{summary['median_horizontal_m']:.1f} m horizontally and "
            f"{summary['median_up_m']:+.1f} m up over {len(shifts)} epochs",
            file=sys.stderr,
        )
    if largest:
        top = largest[0]
        print(
            f"Largest term: {top.system} {top.prn} e={top.eccentricity:.4f} "
            f"±{top.amplitude_ns:.1f} ns ({top.amplitude_m:.1f} m)",
            file=sys.stderr,
        )
    return 0 if shifts else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
