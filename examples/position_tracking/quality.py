"""Receiver DOP and satellite signal reports for position tracks."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import cast

from um982py.capture import record_epoch
from um982py.messages.enums import SatelliteSystem
from um982py.messages.record import Record
from um982py.stats import mean, percentile, stddev

DOP_FIELDS = ("gdop", "pdop", "tdop", "vdop", "hdop", "ndop", "edop")


def summary_statistics(values: Sequence[float]) -> dict[str, float | int | None]:
    finite = [value for value in values if math.isfinite(value)]
    return {
        "count": len(finite),
        "minimum": min(finite) if finite else None,
        "mean": mean(finite) if finite else None,
        "median": percentile(finite, 0.5) if finite else None,
        "p95": percentile(finite, 0.95) if finite else None,
        "maximum": max(finite) if finite else None,
        "standard_deviation": stddev(finite) if len(finite) > 1 else None,
    }


def dop_report(captured: Mapping[str, Sequence[Record]]) -> dict[str, object]:
    epochs: list[dict[str, object]] = []
    by_log: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {name: [] for name in DOP_FIELDS}
    )
    for name in ("STADOP", "PPPDOP"):
        for record in captured.get(name, ()):
            source = record.name
            values = {field: record.real(field) for field in DOP_FIELDS}
            reported_prns = record.get("prn")
            valid = record.integer("count_prn") > 0 and all(
                math.isfinite(value) and value >= 0 for value in values.values()
            )
            epochs.append(
                {
                    "time_gps_s": record_epoch(record),
                    "source": source,
                    "valid": valid,
                    "used_satellites": record.integer("count_prn"),
                    "cutoff_reported": record.real("cutoff"),
                    "used_prns": [prn for prn in reported_prns if isinstance(prn, int)]
                    if isinstance(reported_prns, tuple)
                    else [],
                    **values,
                }
            )
            if valid:
                for field, value in values.items():
                    by_log[source][field].append(value)
    epochs.sort(
        key=lambda row: (cast(float, row["time_gps_s"]), cast(str, row["source"]))
    )
    return {
        "epochs": epochs,
        "statistics": {
            source: {
                field: summary_statistics(values) for field, values in fields.items()
            }
            for source, fields in by_log.items()
        },
    }


def _system_name(code: int) -> str:
    try:
        return SatelliteSystem(code).name
    except ValueError:
        return str(code)


def satellite_report(records: Sequence[Record]) -> dict[str, object]:
    epochs: list[dict[str, object]] = []
    unique: dict[str, set[int]] = defaultdict(set)
    signals: Counter[tuple[str, int]] = Counter()
    snr_values: list[float] = []
    counts: list[float] = []
    for record in records:
        satellites: list[dict[str, object]] = []
        for satellite in record.records("satellites"):
            prn = satellite.integer("prn")
            frequencies: list[dict[str, object]] = []
            systems: set[str] = set()
            for frequency in satellite.records("frequencies"):
                system = _system_name(frequency.integer("system"))
                signal = frequency.integer("signal")
                snr = frequency.real("snr")
                systems.add(system)
                unique[system].add(prn)
                signals[system, signal] += 1
                if math.isfinite(snr) and snr > 0:
                    snr_values.append(snr)
                frequencies.append(
                    {
                        "system": system,
                        "signal": signal,
                        "snr_reported": snr,
                        "reported_frequency_count": frequency.integer(
                            "frequency_count"
                        ),
                    }
                )
            satellites.append(
                {
                    "prn": prn,
                    "systems": sorted(systems),
                    "azimuth_deg": satellite.real("azimuth"),
                    "elevation_deg": satellite.real("elevation"),
                    "frequencies": frequencies,
                }
            )
        counts.append(float(len(satellites)))
        epochs.append(
            {
                "time_gps_s": record_epoch(record),
                "reported_satellites": record.integer("satellite_count"),
                "frequency_flags": record.integer("frequency_flags"),
                "satellites": satellites,
            }
        )
    epochs.sort(key=lambda row: cast(float, row["time_gps_s"]))
    return {
        "epochs": epochs,
        "statistics": {
            "frames": len(epochs),
            "tracked_satellites_per_frame": summary_statistics(counts),
            "unique_satellites": sum(len(prns) for prns in unique.values()),
            "unique_by_system": {
                name: len(prns) for name, prns in sorted(unique.items())
            },
            "signal_observations": {
                f"{system}:{signal}": count
                for (system, signal), count in sorted(signals.items())
            },
            "snr_reported": summary_statistics(snr_values),
        },
        "meaning": (
            "SATSINFO is receiver-wide tracked-signal data, not a list of "
            "satellites used in a position fix."
        ),
    }
