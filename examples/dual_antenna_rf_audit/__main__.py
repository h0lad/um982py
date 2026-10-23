"""Compare both active antenna paths without changing RF power or signal groups."""

import csv
import importlib
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.dual_antenna_rf_audit import (
    compare_antennas,
    paired_observation_details,
    summarize_by_elevation,
    summarize_by_signal,
)
from um982py.antenna import AntennaLog
from um982py.capture import capture_logs
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.diagnostics import signal_inventory
from um982py.experimental import FirmwareLog


def main(argv: Sequence[str] | None = None) -> int:
    """Report paired C/N0 differences with the chosen antenna as the numerator."""
    parser = experiment_parser(
        "dual_antenna_rf_audit", "Synchronous multi-GNSS ANT1/ANT2 reception comparison"
    )
    parser.add_argument("--ant1-type")
    parser.add_argument("--ant2-type")
    parser.add_argument("--ant1-cable-m", type=float)
    parser.add_argument("--ant2-cable-m", type=float)
    parser.add_argument("--pairs-csv", type=Path)
    parser.add_argument("--elevation-csv", type=Path)
    parser.add_argument("--measurements-csv", type=Path)
    parser.add_argument(
        "--plot", type=Path, help="save paired C/N0 differences (requires matplotlib)"
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    paths = [
        path
        for path in (
            args.replay,
            args.record,
            args.json,
            args.pairs_csv,
            args.elevation_csv,
            args.measurements_csv,
            args.plot,
        )
        if path is not None
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("input, output and report paths must be distinct")
    debug_header(args, "dual_antenna_rf_audit")
    for cable in (args.ant1_cable_m, args.ant2_cable_m):
        if cable is not None and not 0 <= cable < float("inf"):
            parser.error("cable lengths must be finite and nonnegative")
    data = capture_logs(
        args,
        [
            AntennaLog(FirmwareLog.RANGE, FirmwareLog.RANGE),
            AntennaLog(FirmwareLog.RANGEH, FirmwareLog.RANGEH),
            FirmwareLog.SATVIS2,
        ],
        on_progress=progress_printer("dual_antenna_rf_audit") if args.debug else None,
    )
    selected = 2 if args.antenna in ("secondary", "2") else 1
    first, second = ("RANGE", "RANGEH") if selected == 1 else ("RANGEH", "RANGE")
    result = compare_antennas(data[first], data[second])
    elevation = summarize_by_elevation(result, data["SATVIS2"])
    details = paired_observation_details(data[first], data[second])
    if args.plot is not None:
        try:
            plt = importlib.import_module("matplotlib.pyplot")
        except ImportError as error:
            raise ValueError("--plot requires matplotlib") from error
        figure, axis = plt.subplots(figsize=(10, 4))
        for system in sorted({item.key.system for item in result.pairs}):
            points = [item for item in result.pairs if item.key.system == system]
            axis.scatter(
                [item.epoch for item in points],
                [item.difference_db for item in points],
                s=6,
                label=f"system {system}",
            )
        axis.set_xlabel("GPS seconds since 1980-01-06")
        axis.set_ylabel("Selected minus other C/N0 (dB)")
        if result.pairs:
            axis.legend()
        figure.tight_layout()
        figure.savefig(args.plot)
        plt.close(figure)
    if args.measurements_csv is not None:
        args.measurements_csv.parent.mkdir(parents=True, exist_ok=True)
        columns = (
            "epoch_gps_seconds",
            "system",
            "prn",
            "signal",
            "l2c_flag",
            "frequency_channel",
            "cn0_difference_db",
            "pseudorange_difference_m",
            "raw_phase_difference_cycles",
            "doppler_difference_hz",
            "selected_lock_seconds",
            "other_lock_seconds",
        )
        with args.measurements_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(details)
    if args.pairs_csv is not None:
        args.pairs_csv.parent.mkdir(parents=True, exist_ok=True)
        args.pairs_csv.write_text(
            "gps_epoch,system,prn,signal,l2c_flag,selected_cn0_db_hz,"
            "other_cn0_db_hz,difference_db\n"
            + "".join(
                f"{item.epoch:.3f},{item.key.system},{item.key.prn},"
                f"{item.key.signal},{item.key.l2c_flag},"
                f"{item.selected_cn0_db_hz:.3f},{item.other_cn0_db_hz:.3f},"
                f"{item.difference_db:.3f}\n"
                for item in result.pairs
            ),
            encoding="ascii",
        )
    if args.elevation_csv is not None:
        args.elevation_csv.parent.mkdir(parents=True, exist_ok=True)
        args.elevation_csv.write_text(
            "system,signal,l2c_flag,elevation_min_deg,elevation_max_deg,"
            "satellites,pairs,median_difference_db,satellite_p10_db,satellite_p90_db\n"
            + "".join(
                f"{item.system},{item.signal},{item.l2c_flag},"
                f"{item.elevation_min_deg},{item.elevation_max_deg},"
                f"{item.satellites},{item.pairs},{item.median_difference_db:.3f},"
                f"{item.satellite_p10_db:.3f},{item.satellite_p90_db:.3f}\n"
                for item in elevation
            ),
            encoding="ascii",
        )
    payload = {
        "status": "ok" if result.pairs else "no_synchronous_pairs",
        "selected_antenna": selected,
        "difference_convention": "selected minus other antenna, dB",
        "antenna_metadata": {
            "ant1_type": args.ant1_type,
            "ant2_type": args.ant2_type,
            "ant1_cable_m": args.ant1_cable_m,
            "ant2_cable_m": args.ant2_cable_m,
        },
        "limitation": (
            "C/N0 differences include sky view, multipath, cable, LNA and RF-path "
            "effects, so they are not calibrated antenna gain or measured "
            "bias voltage. "
            "Only code-locked observations with positive finite C/N0 are paired."
        ),
        "signal_summaries": [asdict(item) for item in summarize_by_signal(result)],
        "measurement_pairs": details,
        "elevation_summaries": [asdict(item) for item in elevation],
        "pairs_without_unique_elevation": len(result.pairs)
        - sum(item.pairs for item in elevation),
        "antenna_inventories": {
            "selected": signal_inventory(data[first]),
            "other": signal_inventory(data[second]),
        },
        **asdict(result),
    }
    print(
        f"Dual-antenna RF audit: {len(result.pairs)} synchronous pairs; "
        f"selected antenna {selected}",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0 if result.pairs else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
