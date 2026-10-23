"""Compares both antenna reception paths signal by signal."""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from um982py.capture import record_epoch
from um982py.messages import Record
from um982py.signals import tracking_signal
from um982py.stats import percentile


@dataclass(frozen=True, slots=True, order=True)
class ReceptionKey:
    """A native satellite and signal identity retaining L2C and FDMA distinctions."""

    system: int
    prn: int
    signal: int
    l2c_flag: int
    frequency_channel: int


@dataclass(frozen=True, slots=True)
class ReceptionPair:
    """Two code-locked C/N0 measurements at exactly the same receiver epoch."""

    epoch: float
    key: ReceptionKey
    selected_cn0_db_hz: float
    other_cn0_db_hz: float
    difference_db: float


@dataclass(frozen=True, slots=True)
class ReceptionSummary:
    """Paired temporal statistics for one native signal on one satellite."""

    key: ReceptionKey
    constellation: str
    signal_name: str
    pairs: int
    median_difference_db: float
    mad_difference_db: float


@dataclass(frozen=True, slots=True)
class SignalBandSummary:
    """Paired C/N0 difference statistics aggregated by constellation and signal."""

    system: int
    signal: int
    l2c_flag: int
    constellation: str
    signal_name: str
    frequency_hz: float | None
    satellites: int
    pairs: int
    median_difference_db: float
    mad_difference_db: float


@dataclass(frozen=True, slots=True)
class AntennaComparison:
    """Synchronous pairs and unmatched observations from both reception paths."""

    selected_epochs: int
    other_epochs: int
    matched_epochs: int
    selected_only_observations: int
    other_only_observations: int
    pairs: tuple[ReceptionPair, ...]
    satellites: tuple[ReceptionSummary, ...]


@dataclass(frozen=True, slots=True)
class ElevationSummary:
    system: int
    signal: int
    l2c_flag: int
    elevation_min_deg: int
    elevation_max_deg: int
    satellites: int
    pairs: int
    median_difference_db: float
    satellite_p10_db: float
    satellite_p90_db: float


def paired_observation_details(
    selected: Sequence[Record], other: Sequence[Record]
) -> tuple[dict[str, object], ...]:
    """Pair valid code-locked rows whose raw phase differences include ambiguities."""

    def index(records: Sequence[Record]) -> dict[tuple[float, ReceptionKey], Record]:
        result: dict[tuple[float, ReceptionKey], Record] = {}
        for record in records:
            epoch = record_epoch(record)
            for row in record.records("observations"):
                status = row.integer("tracking_status")
                cn0 = row.real("cn0")
                if not status & 0x1000 or not math.isfinite(cn0) or cn0 <= 0:
                    continue
                system, signal = (status >> 16) & 7, (status >> 21) & 31
                key = ReceptionKey(
                    system,
                    row.integer("prn"),
                    signal,
                    int(bool(status & (1 << 26)))
                    if system in (0, 5) and signal == 9
                    else 0,
                    row.integer("frequency_channel") if system == 1 else 0,
                )
                identity = (epoch, key)
                old = result.get(identity)
                if old is None or cn0 > old.real("cn0"):
                    result[identity] = row
        return result

    first, second = index(selected), index(other)
    output: list[dict[str, object]] = []
    for epoch, key in sorted(first.keys() & second.keys()):
        a, b = first[(epoch, key)], second[(epoch, key)]
        phase_ok = bool(
            a.integer("tracking_status") & b.integer("tracking_status") & 0x400
        )
        output.append(
            {
                "epoch_gps_seconds": epoch,
                "system": key.system,
                "prn": key.prn,
                "signal": key.signal,
                "l2c_flag": key.l2c_flag,
                "frequency_channel": key.frequency_channel,
                "cn0_difference_db": a.real("cn0") - b.real("cn0"),
                "pseudorange_difference_m": a.real("pseudorange")
                - b.real("pseudorange"),
                "raw_phase_difference_cycles": a.real("carrier_phase")
                - b.real("carrier_phase")
                if phase_ok
                else None,
                "doppler_difference_hz": a.real("doppler") - b.real("doppler")
                if phase_ok
                else None,
                "selected_lock_seconds": a.real("lock_time"),
                "other_lock_seconds": b.real("lock_time"),
            }
        )
    return tuple(output)


def _receptions(records: Sequence[Record]) -> dict[float, dict[ReceptionKey, float]]:
    result: dict[float, dict[ReceptionKey, float]] = {}
    previous = -math.inf
    for record in records:
        epoch = record_epoch(record)
        if epoch <= previous:
            raise ValueError("each antenna needs strictly increasing RANGE epochs")
        previous = epoch
        observations: dict[ReceptionKey, float] = {}
        for row in record.records("observations"):
            status, cn0 = row.integer("tracking_status"), row.real("cn0")
            if not status & (1 << 12) or not math.isfinite(cn0) or cn0 <= 0:
                continue
            system, signal = (status >> 16) & 7, (status >> 21) & 31
            key = ReceptionKey(
                system,
                row.integer("prn"),
                signal,
                int(bool(status & (1 << 26)))
                if system in (0, 5) and signal == 9
                else 0,
                row.integer("frequency_channel") if system == 1 else 0,
            )
            observations[key] = max(cn0, observations.get(key, cn0))
        result[epoch] = observations
    return result


def compare_antennas(
    selected: Sequence[Record], other: Sequence[Record]
) -> AntennaComparison:
    """Pair identical epochs and signals without imputing absent measurements."""
    first, second = _receptions(selected), _receptions(other)
    pairs: list[ReceptionPair] = []
    selected_only = other_only = 0
    for epoch in sorted(first.keys() | second.keys()):
        a, b = first.get(epoch, {}), second.get(epoch, {})
        selected_only += len(a.keys() - b.keys())
        other_only += len(b.keys() - a.keys())
        pairs.extend(
            ReceptionPair(epoch, key, a[key], b[key], a[key] - b[key])
            for key in sorted(a.keys() & b.keys())
        )
    groups: dict[ReceptionKey, list[float]] = defaultdict(list)
    for pair in pairs:
        groups[pair.key].append(pair.difference_db)
    summary = []
    for key, differences in sorted(groups.items()):
        status = (key.system << 16) | (key.signal << 21) | (key.l2c_flag << 26)
        identity = tracking_signal(status) if key.system <= 6 else None
        center = median(differences)
        summary.append(
            ReceptionSummary(
                key,
                identity.constellation if identity else "unknown",
                identity.name if identity else "unknown",
                len(differences),
                center,
                median(abs(value - center) for value in differences),
            )
        )
    return AntennaComparison(
        len(first),
        len(second),
        len(first.keys() & second.keys()),
        selected_only,
        other_only,
        tuple(pairs),
        tuple(summary),
    )


def summarize_by_signal(
    comparison: AntennaComparison,
) -> tuple[SignalBandSummary, ...]:
    """Pool paired C/N0 differences across satellites for each tracked signal band."""
    grouped: dict[tuple[int, int, int], list[ReceptionPair]] = defaultdict(list)
    for pair in comparison.pairs:
        band_key = (pair.key.system, pair.key.signal, pair.key.l2c_flag)
        grouped[band_key].append(pair)
    summaries: list[SignalBandSummary] = []
    for (system, signal, l2c_flag), band_pairs in sorted(grouped.items()):
        status = (system << 16) | (signal << 21) | (l2c_flag << 26)
        identity = tracking_signal(status) if system <= 6 else None
        differences = [pair.difference_db for pair in band_pairs]
        center = median(differences)
        summaries.append(
            SignalBandSummary(
                system=system,
                signal=signal,
                l2c_flag=l2c_flag,
                constellation=identity.constellation if identity else "unknown",
                signal_name=identity.name if identity else "unknown",
                frequency_hz=identity.frequency_hz if identity else None,
                satellites=len({pair.key.prn for pair in band_pairs}),
                pairs=len(differences),
                median_difference_db=center,
                mad_difference_db=median(abs(value - center) for value in differences),
            )
        )
    return tuple(summaries)


def summarize_by_elevation(
    comparison: AntennaComparison, visibility: Sequence[Record]
) -> tuple[ElevationSummary, ...]:
    systems = {
        "GPS": 0,
        "GLONASS": 1,
        "SBAS": 2,
        "GALILEO": 3,
        "BEIDOU": 4,
        "QZSS": 5,
        "NAVIC": 6,
    }
    geometry: dict[tuple[float, int, int], list[float]] = defaultdict(list)
    for record in visibility:
        system = record["constellation"]
        if isinstance(system, str):
            system = systems.get(system)
        if not isinstance(system, int) or system not in range(7):
            continue
        epoch = record_epoch(record)
        for satellite in record.records("satellites"):
            elevation = satellite.real("elevation")
            if math.isfinite(elevation) and 0 <= elevation <= 90:
                geometry[epoch, system, satellite.integer("prn")].append(elevation)
    grouped: dict[tuple[int, int, int, int], dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for pair in comparison.pairs:
        key = pair.epoch, pair.key.system, pair.key.prn
        elevations = geometry.get(key, ())
        if len(elevations) != 1:
            continue
        lower = min(int(elevations[0] // 15) * 15, 75)
        band = pair.key.system, pair.key.signal, pair.key.l2c_flag, lower
        grouped[band][pair.key.prn].append(pair.difference_db)
    result = []
    for (system, signal, l2c_flag, lower), by_satellite in sorted(grouped.items()):
        satellite_medians = [median(values) for values in by_satellite.values()]
        result.append(
            ElevationSummary(
                system,
                signal,
                l2c_flag,
                lower,
                lower + 15,
                len(by_satellite),
                sum(map(len, by_satellite.values())),
                median(satellite_medians),
                percentile(satellite_medians, 0.1),
                percentile(satellite_medians, 0.9),
            )
        )
    return tuple(result)
