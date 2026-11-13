"""Select GPS observations and ephemerides for position examples."""

import math
from collections.abc import Sequence

from examples.wls_position import RangeMeasurement
from um982py.capture import gps_signals, record_epoch
from um982py.experimental.orbit import EARTH_ROTATION_RATE, state_from_record
from um982py.geodesy import SPEED_OF_LIGHT, receiver_ecef
from um982py.messages import Record
from um982py.messages.enums import SatelliteSystem

GPS_L1_SIGNAL_TYPE = 0
SATELLITE_SYSTEM_SHIFT = 16
SATELLITE_SYSTEM_MASK = 0b111
SIGNAL_TYPE_SHIFT = 21
SIGNAL_TYPE_MASK = 0b11111
GPS_WEEK_SECONDS = 604800.0
MAX_EPHEMERIS_AGE_SECONDS = 7200.0


def select_position(
    records: Sequence[Record], epoch: float, tolerance: float
) -> Record:
    """Find a computed, finite receiver position near the observation epoch."""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("position tolerance must be finite and non-negative")
    eligible = []
    for record in records:
        if record.get("p_sol_status") not in (0, "SOL_COMPUTED"):
            continue
        try:
            xyz = receiver_ecef(record)
            age = abs(record_epoch(record) - epoch)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            all(math.isfinite(x) for x in xyz)
            and math.dist(xyz, (0, 0, 0)) > 1e6
            and age <= tolerance
        ):
            eligible.append((age, record))
    if not eligible:
        raise ValueError("no valid receiver position within the epoch tolerance")
    return min(eligible, key=lambda item: item[0])[1]


def select_gps_ephemerides(
    records: Sequence[Record], epoch: float, *, ranges: Record | None = None
) -> dict[int, Record]:
    """Choose healthy GPS ephemerides within two hours of the observation."""
    travel_by_prn = (
        {
            item.integer("prn"): item.real("pseudorange") / SPEED_OF_LIGHT
            for item, _ in gps_signals(ranges, [1575.42e6], phase=False)
        }
        if ranges is not None
        else {}
    )
    best: dict[int, tuple[float, Record]] = {}
    for record in records:
        try:
            if record.integer("health") != 0 or record.integer(
                "iode1"
            ) != record.integer("iode2"):
                continue
            toe = record.integer("week") * GPS_WEEK_SECONDS + record.real("toe")
            prn = record.integer("prn")
            age = abs(epoch - travel_by_prn.get(prn, 0.0) - toe)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            math.isfinite(age)
            and age <= MAX_EPHEMERIS_AGE_SECONDS
            and (prn not in best or age < best[prn][0])
        ):
            best[prn] = (age, record)
    return {prn: entry[1] for prn, entry in best.items()}


def gps_l1_measurements(
    record: Record, ephemerides: dict[int, Record], epoch: float
) -> tuple[RangeMeasurement, ...]:
    selected: dict[int, Record] = {}
    for observation, _ in gps_signals(record, [1575.42e6], phase=False):
        tracking = observation.integer("tracking_status")
        system = (tracking >> SATELLITE_SYSTEM_SHIFT) & SATELLITE_SYSTEM_MASK
        signal = (tracking >> SIGNAL_TYPE_SHIFT) & SIGNAL_TYPE_MASK
        prn = observation.integer("prn")
        if system != SatelliteSystem.GPS or signal != GPS_L1_SIGNAL_TYPE:
            continue
        if prn not in ephemerides:
            continue
        current = selected.get(prn)
        if current is None or observation.real("cn0") > current.real("cn0"):
            selected[prn] = observation
    measurements = []
    for prn, observation in sorted(selected.items()):
        ephemeris = ephemerides[prn]
        travel = observation.real("pseudorange") / SPEED_OF_LIGHT
        state = state_from_record(ephemeris, epoch - travel - ephemeris.real("toe"))
        state = state_from_record(
            ephemeris, epoch - travel - state.clock_bias - ephemeris.real("toe")
        )
        rotation = EARTH_ROTATION_RATE * travel
        rotated_x = math.cos(rotation) * state.x + math.sin(rotation) * state.y
        rotated_y = -math.sin(rotation) * state.x + math.cos(rotation) * state.y
        measurements.append(
            RangeMeasurement(
                system=SatelliteSystem.GPS,
                prn=prn,
                x=rotated_x,
                y=rotated_y,
                z=state.z,
                pseudorange=observation.real("pseudorange"),
                pseudorange_std=observation.real("pseudorange_std"),
                satellite_clock=state.clock_bias,
            )
        )
    return tuple(measurements)
