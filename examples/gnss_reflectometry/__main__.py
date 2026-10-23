"""Capture or replay a multi-GNSS, dual-antenna reflectometry experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from examples.dual_antenna_rf_audit import compare_antennas, summarize_by_signal
from examples.gnss_reflectometry import (
    MAX_ELEVATION_DEGREES,
    MAX_HEIGHT_METRES,
    MIN_ELEVATION_DEGREES,
    MIN_HEIGHT_METRES,
    ReflectometryJoin,
    SatelliteSample,
    join_observations,
    segment_arcs,
)
from examples.gnss_reflectometry.report import (
    QualityCriteria,
    automatic_height,
    build_dual_payload,
    build_payload,
    compare_reference,
    reflection_coverage,
    signal_labels,
)
from examples.satellite_monitor import Constellation
from um982py import export_rinex
from um982py.antenna import AntennaLog, antenna_index, antenna_log
from um982py.capture import DataLog, capture_records, record_epoch
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.diagnostics import signal_inventory
from um982py.experimental import FirmwareLog
from um982py.messages.enums import PositionType
from um982py.messages.record import Record

__all__ = [
    "TRACKING_SYSTEMS",
    "automatic_height",
    "build_dual_payload",
    "build_payload",
    "epoch_samples",
    "main",
    "reflection_coverage",
    "signal_labels",
]

TRACKING_SYSTEMS = {
    Constellation.GPS: 0,
    Constellation.GLONASS: 1,
    Constellation.SBAS: 2,
    Constellation.GALILEO: 3,
    Constellation.BEIDOU: 4,
    Constellation.QZSS: 5,
    Constellation.NAVIC: 6,
}
TELEMETRY_LOGS: tuple[Log | FirmwareLog, ...] = (
    Log.JAMSTATUS,
    Log.FREQJAMSTATUS,
    FirmwareLog.SPOOFINFO,
    FirmwareLog.ANTENNASTATUS,
    FirmwareLog.BSLNENUHD,
    Log.PPPNAV,
)


def epoch_samples(
    ranges: Sequence[Record],
    visibility: Sequence[Record],
    *,
    frequency_hz: float | None = None,
    systems: Sequence[int] | None = None,
    signals: Sequence[int] | None = None,
    min_cn0: float = 0.0,
) -> ReflectometryJoin:
    """Join timestamped constellation geometry without interpolating missing skies."""
    sky: dict[float, list[tuple[int, Record]]] = defaultdict(list)
    omitted: Counter[str] = Counter()
    for record in visibility:
        code = record["constellation"]
        if not isinstance(code, (int, str)):
            raise ValueError("invalid SATVIS2 constellation")
        try:
            system = TRACKING_SYSTEMS[Constellation.from_value(code)]
        except ValueError:
            omitted["unknown_satvis_constellation"] += 1
            continue
        sky[record_epoch(record)].extend(
            (system, row) for row in record.records("satellites")
        )
    epochs = sorted(sky)
    samples: list[SatelliteSample] = []
    ambiguous: set[tuple[int, int]] = set()
    previous = -math.inf
    for record in ranges:
        epoch = record_epoch(record)
        if not math.isfinite(epoch) or epoch <= previous:
            raise ValueError("RANGE epochs must increase strictly per antenna")
        previous = epoch
        matching = [
            row
            for time in epochs[
                bisect_left(epochs, epoch - 0.001) : bisect_right(epochs, epoch + 0.001)
            ]
            for row in sky[time]
        ]
        joined = join_observations(
            record.records("observations"), matching, time_s=epoch
        )
        for sample in joined.samples:
            if (
                (frequency_hz is None or abs(sample.frequency_hz - frequency_hz) < 1)
                and (systems is None or sample.system in systems)
                and (signals is None or sample.signal in signals)
                and sample.cn0 >= min_cn0
            ):
                samples.append(sample)
            else:
                omitted["selection_filter"] += 1
        ambiguous.update(joined.ambiguous_satellites)
        omitted.update(joined.omitted)
    return ReflectometryJoin(tuple(samples), tuple(sorted(ambiguous)), dict(omitted))


def telemetry_summary(records: Mapping[str, tuple[Record, ...]]) -> dict[str, object]:
    """Summarize recorded receiver health without inferring reflected-signal quality."""
    position_types: Counter[str] = Counter()
    for row in records.get("PPPNAV", ()):
        kind = row.get("pos_type")
        label = (
            PositionType(kind).name
            if isinstance(kind, int) and kind in PositionType
            else str(kind)
        )
        position_types[label] += 1
    return {
        "record_counts": {
            log.value: len(records.get(log.value, ())) for log in TELEMETRY_LOGS
        },
        "ppp_position_types": dict(position_types),
        "spoof_indicator_epochs": sum(
            bool(row.get("spoof_indicator")) for row in records.get("SPOOFINFO", ())
        ),
        "jamming_flag_epochs": {
            name: sum(
                any(bool(row.get(field)) for field in fields)
                for row in records.get(name, ())
            )
            for name, fields in (
                ("JAMSTATUS", ("cwflag",)),
                ("FREQJAMSTATUS", ("l1cwflag", "l2cwflag", "l5cwflag")),
            )
        },
        "antenna_status_latest": dict(records["ANTENNASTATUS"][-1])
        if records.get("ANTENNASTATUS")
        else None,
        "baseline_latest": dict(records["BSLNENUHD"][-1])
        if records.get("BSLNENUHD")
        else None,
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.gnss_reflectometry",
        description="Multi-GNSS reflector heights, phase fits and Fresnel footprints",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--single-antenna",
        action="store_true",
        help="capture only --antenna instead of both physical inputs",
    )
    parser.add_argument(
        "--duration", type=float, default=3600.0, help="capture seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=5.0, help="log cadence seconds"
    )
    parser.add_argument(
        "--system",
        action="append",
        choices=[system.value for system in Constellation],
        help="select constellations by repeating this option, defaulting to all",
    )
    parser.add_argument(
        "--signal", type=int, action="append", help="native signal ID, repeatable"
    )
    parser.add_argument(
        "--frequency",
        type=float,
        help="filter one carrier frequency in Hz, defaulting to all known carriers",
    )
    parser.add_argument(
        "--min-cn0", type=float, default=0.0, help="C/N0 selection floor in dB-Hz"
    )
    parser.add_argument("--min-elevation", type=float, default=MIN_ELEVATION_DEGREES)
    parser.add_argument("--max-elevation", type=float, default=MAX_ELEVATION_DEGREES)
    parser.add_argument("--min-height", type=float, default=MIN_HEIGHT_METRES)
    parser.add_argument("--max-height", type=float, default=MAX_HEIGHT_METRES)
    parser.add_argument(
        "--azimuth-start",
        type=float,
        default=0.0,
        help="clockwise sector start, allowing wraparound",
    )
    parser.add_argument("--azimuth-end", type=float, default=360.0)
    parser.add_argument(
        "--max-gap",
        type=float,
        help="arc gap in seconds, defaulting to three times the interval",
    )
    parser.add_argument("--peak-to-noise", type=float, default=2.7)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument(
        "--min-span", type=float, default=5.0, help="minimum elevation span in degrees"
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=60.0,
        help="minimum arc duration in seconds",
    )
    parser.add_argument(
        "--min-amplitude",
        type=float,
        default=0.0,
        help="fitted amplitude in linear C/N0 units",
    )
    parser.add_argument("--min-fit-r2", type=float, default=0.0)
    parser.add_argument(
        "--reference-height-ant1",
        type=float,
        help="measured ANT1-to-surface height in metres",
    )
    parser.add_argument(
        "--reference-height-ant2",
        type=float,
        help="measured ANT2-to-surface height in metres",
    )
    parser.add_argument(
        "--reference-json",
        type=Path,
        help="previous report for matched-pass interference phase differences",
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="also capture antenna, baseline, PPP, jamming and spoofing status",
    )
    parser.add_argument("--csv", type=Path, help="per-arc scalar results")
    parser.add_argument(
        "--samples-csv",
        type=Path,
        help="joined native signal observations and sky angles",
    )
    parser.add_argument("--spectra-csv", type=Path, help="per-arc height periodograms")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print capture, join, arc and export diagnostics to stderr",
    )
    parser.add_argument(
        "--rinex-dir",
        type=Path,
        help="export native observations as separate antenna RINEX 3.05 files",
    )
    parser.add_argument(
        "--l2c-code",
        choices=("2S", "2L", "2X"),
        help="independently identified L2C component for RINEX",
    )
    return parser


def _validate(parser: ExampleParser, args: argparse.Namespace) -> None:
    numeric = (
        args.duration,
        args.interval,
        args.timeout,
        args.min_height,
        args.max_height,
        args.min_cn0,
        args.peak_to_noise,
        args.min_span,
        args.min_duration,
        args.min_amplitude,
        args.min_fit_r2,
    )
    optional = (
        args.frequency,
        args.max_gap,
        args.reference_height_ant1,
        args.reference_height_ant2,
    )
    if not all(math.isfinite(value) for value in numeric) or any(
        value is not None and (not math.isfinite(value) or value <= 0)
        for value in optional
    ):
        parser.error(
            "numeric options must be finite; frequency, gap and reference heights "
            "must be positive"
        )
    if (
        min(
            args.duration,
            args.interval,
            args.timeout,
            args.min_height,
            args.peak_to_noise,
            args.min_span,
        )
        <= 0
        or args.max_height <= args.min_height
    ):
        parser.error(
            "duration, interval, timeout, thresholds and height bounds "
            "must be positive and ordered"
        )
    if (
        args.min_samples < 3
        or args.min_duration < 0
        or args.min_amplitude < 0
        or not 0 <= args.min_fit_r2 <= 1
        or not 0 <= args.min_cn0 <= 100
    ):
        parser.error("invalid arc quality thresholds")
    if args.signal is not None and any(not 0 <= code <= 31 for code in args.signal):
        parser.error("native signal IDs must be in 0..31")
    try:
        segment_arcs(
            (),
            min_elevation=args.min_elevation,
            max_elevation=args.max_elevation,
            azimuth_start=args.azimuth_start,
            azimuth_end=args.azimuth_end,
            max_gap_s=args.max_gap or 3 * args.interval,
        )
    except ValueError as error:
        parser.error(str(error))
    paths = [
        path
        for path in (
            args.json,
            args.csv,
            args.samples_csv,
            args.spectra_csv,
            args.replay,
            args.record,
            args.reference_json,
        )
        if path is not None
    ]
    if args.rinex_dir is not None:
        paths.extend(args.rinex_dir / f"{antenna}.obs" for antenna in ("ANT1", "ANT2"))
    if len(paths) != len({path.resolve() for path in paths}):
        parser.error("input, capture and output paths must be distinct")


def _write_csv(
    path: Path, rows: Sequence[dict[str, object]], columns: Sequence[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"gnss_reflectometry debug: {message}", file=sys.stderr, flush=True)


def _debug_report(report: Mapping[str, object]) -> None:
    antennas = cast(dict[str, dict[str, object]], report["antennas"])
    for antenna, result in antennas.items():
        arcs = cast(list[dict[str, object]], result["arcs"])
        _debug(
            True,
            f"{antenna}: status={result['status']}, samples={result['samples']}, "
            f"arcs={len(arcs)}, accepted={result['accepted_arcs']}, "
            f"rejections={result['rejection_counts']}",
        )
        for arc in arcs:
            label = (
                f"{arc['constellation']} {arc['prn']} {arc['signal_name']} "
                f"{arc['direction']} at {arc['start_gps_s']} GPS s"
            )
            outcome = (
                f"height={cast(float, arc['height_m']):.3f} m, "
                f"peak/noise={cast(float, arc['peak_to_noise']):.2f}"
                if arc["rejection"] is None
                else f"rejected={arc['rejection']}"
            )
            _debug(
                True,
                f"{antenna} {label}: samples={arc['samples']}, "
                f"span={cast(float, arc['elevation_span_deg']):.1f} deg, {outcome}",
            )


def _exports(
    args: argparse.Namespace,
    report: dict[str, object],
    joined: Mapping[str, ReflectometryJoin],
    sources: Mapping[str, tuple[Record, ...]],
) -> None:
    antennas = cast(dict[str, dict[str, object]], report["antennas"])
    rows = [
        dict(row, antenna=name)
        for name, antenna in antennas.items()
        for row in cast(list[dict[str, object]], antenna["arcs"])
    ]
    if args.csv is not None:
        _write_csv(
            args.csv,
            rows,
            (
                "antenna",
                "system",
                "prn",
                "signal",
                "l2c_flag",
                "frequency_hz",
                "direction",
                "start_gps_s",
                "end_gps_s",
                "samples",
                "duration_s",
                "elevation_span_deg",
                "height_m",
                "reference_error_m",
                "peak_to_noise",
                "height_resolution_m",
                "rejection",
            ),
        )
    if args.samples_csv is not None:
        _write_csv(
            args.samples_csv,
            [
                dict(asdict(sample), antenna=name)
                for name, series in joined.items()
                for sample in series.samples
            ],
            (
                "antenna",
                "system",
                "prn",
                "signal",
                "l2c_flag",
                "frequency_hz",
                "time_s",
                "elevation",
                "azimuth",
                "cn0",
                "lock_seconds",
            ),
        )
    if args.spectra_csv is not None:
        _write_csv(
            args.spectra_csv,
            [
                dict(
                    point,
                    antenna=row["antenna"],
                    system=row["system"],
                    prn=row["prn"],
                    signal=row["signal"],
                    l2c_flag=row["l2c_flag"],
                    start_gps_s=row["start_gps_s"],
                    rejection=row["rejection"],
                )
                for row in rows
                for point in cast(list[dict[str, object]], row.get("spectrum", []))
            ],
            (
                "antenna",
                "system",
                "prn",
                "signal",
                "l2c_flag",
                "start_gps_s",
                "height_m",
                "lomb_power",
                "rejection",
            ),
        )
    if args.rinex_dir is not None:
        exports = []
        for antenna, records in sources.items():
            if not records:
                continue
            result = export_rinex(
                records, marker_name=f"GNSSIR-{antenna}", l2c_code=args.l2c_code
            )
            destination = args.rinex_dir / f"{antenna}.obs"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(result.text, encoding="ascii")
            exports.append(
                {
                    "antenna": antenna,
                    "path": str(destination),
                    "epochs": result.epochs,
                    "omitted": result.omitted,
                }
            )
        report["rinex_exports"] = exports


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    reference = None
    if args.reference_json is not None:
        reference = json.loads(args.reference_json.read_text(encoding="utf-8"))
        if not isinstance(reference, dict) or reference.get("schema_version") != 1:
            parser.error("reference JSON must be a GNSS-IR schema_version 1 report")
    logs: list[DataLog] = (
        [antenna_log(FirmwareLog.RANGE, args.antenna)]
        if args.single_antenna
        else [
            AntennaLog(FirmwareLog.RANGE, FirmwareLog.RANGE),
            AntennaLog(FirmwareLog.RANGEH, FirmwareLog.RANGEH),
        ]
    )
    logs.append(AntennaLog(FirmwareLog.SATVIS2, FirmwareLog.SATVIS2))
    if args.telemetry:
        logs.extend(AntennaLog(log, log) for log in TELEMETRY_LOGS)
    source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
    _debug(
        args.debug,
        f"source={source}; "
        f"logs={','.join(log.value for log in logs)}; "
        f"elevation={args.min_elevation:g}..{args.max_elevation:g} deg; "
        f"height={args.min_height:g}..{args.max_height:g} m",
    )
    data = capture_records(args, logs, duration=args.duration, interval=args.interval)
    _debug(
        args.debug,
        "decoded records: "
        + ", ".join(f"{name}={len(rows)}" for name, rows in data.items()),
    )
    sources = {
        antenna: tuple(
            record
            for name, records in data.items()
            if name in ("RANGE", "RANGEH")
            for record in records
            if record.name == wire
        )
        for antenna, wire in (("ANT1", "RANGE"), ("ANT2", "RANGEH"))
    }
    systems = (
        [TRACKING_SYSTEMS[Constellation(name)] for name in args.system]
        if args.system
        else None
    )
    joined = {
        name: epoch_samples(
            records,
            data["SATVIS2"],
            frequency_hz=args.frequency,
            systems=systems,
            signals=args.signal,
            min_cn0=args.min_cn0,
        )
        for name, records in sources.items()
    }
    for name, series in joined.items():
        _debug(
            args.debug,
            f"{name}: RANGE epochs={len(sources[name])}, "
            f"joined samples={len(series.samples)}, "
            f"ambiguous satellites={len(series.ambiguous_satellites)}, "
            f"omitted={series.omitted}",
        )
    quality = QualityCriteria(
        args.peak_to_noise,
        args.min_samples,
        args.min_span,
        args.min_duration,
        args.min_amplitude,
        args.min_fit_r2,
        args.spectra_csv is not None,
    )
    report = build_dual_payload(
        joined["ANT1"],
        joined["ANT2"],
        args.min_elevation,
        args.max_elevation,
        args.min_height,
        args.max_height,
        args.azimuth_start,
        args.azimuth_end,
        args.max_gap or 3 * args.interval,
        args.reference_height_ant1,
        args.reference_height_ant2,
        quality=quality,
    )
    if args.debug:
        _debug_report(report)
    report["selected_antenna"] = (
        3 - antenna_index(args.antenna)
        if args.swap_antennas
        else antenna_index(args.antenna)
    )
    report["capture_counts"] = {name: len(records) for name, records in data.items()}
    report["signal_inventories"] = {
        name: signal_inventory(records) for name, records in sources.items()
    }
    if all(sources.values()):
        paired = compare_antennas(sources["ANT1"], sources["ANT2"])
        report["antenna_comparison"] = {
            "matched_epochs": paired.matched_epochs,
            "paired_observations": len(paired.pairs),
            "signal_summaries": [asdict(row) for row in summarize_by_signal(paired)],
        }
    if args.telemetry:
        report["receiver_telemetry"] = telemetry_summary(data)
    if reference is not None:
        changes = compare_reference(report, reference)
        report["phase_changes"] = changes
        _debug(args.debug, f"matched reference phases={len(changes)}")
    _exports(args, report, joined, sources)
    for name in ("csv", "samples_csv", "spectra_csv"):
        path = getattr(args, name)
        if path is not None:
            _debug(args.debug, f"wrote {name}={path}")
    for exported in cast(list[dict[str, object]], report.get("rinex_exports", [])):
        _debug(
            args.debug,
            f"wrote RINEX {exported['antenna']}={exported['path']} "
            f"epochs={exported['epochs']} omitted={exported['omitted']}",
        )
    write_json(report, args.json)
    _debug(args.debug, f"status={report['status']}; JSON={args.json or 'stdout'}")
    return 0 if report["status"] == "height_estimated" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
