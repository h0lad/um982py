"""Aggregates C/N0, lock time and tracking status per signal."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from um982py.geodesy import records_from
from um982py.messages import Record
from um982py.messages.enums import SatelliteSystem
from um982py.stats import percentile

CHANNEL_NUMBER_SHIFT = 5
CHANNEL_NUMBER_MASK = 0b11111
CARRIER_PHASE_VALID_MASK = 1 << 10
PSEUDORANGE_VALID_MASK = 1 << 12
SATELLITE_SYSTEM_SHIFT = 16
SATELLITE_SYSTEM_MASK = 0b111
SIGNAL_TYPE_SHIFT = 21
SIGNAL_TYPE_MASK = 0b11111
L2C_MASK = 1 << 26


class LockBucket(StrEnum):
    """Continuous carrier lock time bucket."""

    UNDER_ONE_SECOND = "0-1s"
    UNDER_TEN_SECONDS = "1-10s"
    UNDER_ONE_MINUTE = "10-60s"
    UNDER_TEN_MINUTES = "60-600s"
    OVER_TEN_MINUTES = "600s+"


LOCK_BOUNDARIES: tuple[tuple[float, LockBucket], ...] = (
    (1.0, LockBucket.UNDER_ONE_SECOND),
    (10.0, LockBucket.UNDER_TEN_SECONDS),
    (60.0, LockBucket.UNDER_ONE_MINUTE),
    (600.0, LockBucket.UNDER_TEN_MINUTES),
)


@dataclass(frozen=True, slots=True)
class ChannelTracking:
    """Documented bits of the RANGE tracking status word."""

    raw: int

    @property
    def channel_number(self) -> int:
        """Receiver channel carrying the signal, 0..31."""
        return (self.raw >> CHANNEL_NUMBER_SHIFT) & CHANNEL_NUMBER_MASK

    @property
    def carrier_phase_valid(self) -> bool:
        """True when the carrier phase measurement is valid."""
        return bool(self.raw & CARRIER_PHASE_VALID_MASK)

    @property
    def pseudorange_valid(self) -> bool:
        """True when the pseudorange measurement is valid."""
        return bool(self.raw & PSEUDORANGE_VALID_MASK)

    @property
    def satellite_system(self) -> SatelliteSystem | None:
        """Constellation of the signal, ``None`` for the reserved code."""
        code = (self.raw >> SATELLITE_SYSTEM_SHIFT) & SATELLITE_SYSTEM_MASK
        if code == SATELLITE_SYSTEM_MASK:
            return None
        return SatelliteSystem(code)

    @property
    def signal_type(self) -> int:
        """Signal type code, interpreted against the satellite system."""
        return (self.raw >> SIGNAL_TYPE_SHIFT) & SIGNAL_TYPE_MASK

    @property
    def is_l2c(self) -> bool:
        """True when signal type L2P (Y) selects the L2C signal instead."""
        return bool(self.raw & L2C_MASK)


@dataclass(frozen=True, slots=True)
class SignalObservation:
    """One RANGE observation with its tracking status decoded."""

    prn: int
    frequency_channel: int
    """GLONASS frequency channel of the observation, ``0`` for other systems."""
    cn0: float
    """Carrier to noise ratio in dB-Hz."""
    lock_time: float
    """Continuous carrier lock time in seconds."""
    tracking: ChannelTracking


@dataclass(frozen=True, slots=True)
class SignalSummary:
    """Aggregates over the observations of one RANGE epoch."""

    observation_count: int
    cn0_p10: float
    cn0_p50: float
    cn0_p90: float
    lock_counts: Mapping[LockBucket, int]
    channel_counts: Mapping[int, int]
    satellite_system_counts: Mapping[SatelliteSystem | None, int]
    carrier_phase_valid: int
    pseudorange_valid: int


def lock_bucket(lock_time: float) -> LockBucket:
    """Bucket a continuous lock time in seconds."""
    for bound, bucket in LOCK_BOUNDARIES:
        if lock_time < bound:
            return bucket
    return LockBucket.OVER_TEN_MINUTES


def observations_from_record(record: Record) -> tuple[SignalObservation, ...]:
    """Decode every observation of one RANGE record."""
    return tuple(
        SignalObservation(
            prn=observation.integer("prn"),
            frequency_channel=observation.integer("frequency_channel"),
            cn0=observation.real("cn0"),
            lock_time=observation.real("lock_time"),
            tracking=ChannelTracking(observation.integer("tracking_status")),
        )
        for observation in records_from(record, "observations")
    )


def summarise(observations: Sequence[SignalObservation]) -> SignalSummary:
    """Aggregate C/N0, lock time and tracking status of one epoch."""
    if not observations:
        raise ValueError("at least one observation is required")
    cn0 = [observation.cn0 for observation in observations]
    lock_counts = dict.fromkeys(LockBucket, 0)
    channel_counts: dict[int, int] = {}
    satellite_system_counts: dict[SatelliteSystem | None, int] = {}
    for observation in observations:
        lock_counts[lock_bucket(observation.lock_time)] += 1
        channel = observation.frequency_channel
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        system = observation.tracking.satellite_system
        satellite_system_counts[system] = satellite_system_counts.get(system, 0) + 1
    return SignalSummary(
        observation_count=len(observations),
        cn0_p10=percentile(cn0, 0.1),
        cn0_p50=percentile(cn0, 0.5),
        cn0_p90=percentile(cn0, 0.9),
        lock_counts=MappingProxyType(dict(lock_counts)),
        channel_counts=MappingProxyType(dict(sorted(channel_counts.items()))),
        satellite_system_counts=MappingProxyType(dict(satellite_system_counts)),
        carrier_phase_valid=sum(
            observation.tracking.carrier_phase_valid for observation in observations
        ),
        pseudorange_valid=sum(
            observation.tracking.pseudorange_valid for observation in observations
        ),
    )


def as_dict(summary: SignalSummary) -> dict[str, object]:
    """Render a signal summary as JSON-ready data."""
    return {
        "observation_count": summary.observation_count,
        "cn0_db_hz": {
            "p10": summary.cn0_p10,
            "p50": summary.cn0_p50,
            "p90": summary.cn0_p90,
        },
        "lock_seconds": {
            str(bucket): count for bucket, count in summary.lock_counts.items()
        },
        "frequency_channel": {
            str(channel): count for channel, count in summary.channel_counts.items()
        },
        "satellite_system": {
            _system_name(system): count
            for system, count in summary.satellite_system_counts.items()
        },
        "carrier_phase_valid": summary.carrier_phase_valid,
        "pseudorange_valid": summary.pseudorange_valid,
    }


def _system_name(system: SatelliteSystem | None) -> str:
    """JSON key of a satellite system."""
    return "reserved" if system is None else system.name
