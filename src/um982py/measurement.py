"""Timestamped GPS measurements with a range-increasing carrier."""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from um982py.geodesy import SPEED_OF_LIGHT
from um982py.messages import (
    AsciiHeader,
    AsciiMessage,
    BinaryHeader,
    BinaryMessage,
    LegacyAsciiHeader,
    LegacyBinaryHeader,
    Message,
    Record,
)
from um982py.signals import tracking_signal

__all__ = [
    "RangeSample",
    "SignalKey",
    "bdt_week_to_gps_seconds",
    "gnss_range_samples",
    "gps_epoch",
    "range_samples",
    "sample_series",
]

GPS_CARRIERS = {0: 1_575_420_000.0, 14: 1_176_450_000.0}


@dataclass(frozen=True, slots=True, order=True)
class SignalKey:
    """Identifies the constellation, PRN and signal of one observable."""

    system: int
    prn: int
    signal: int


@dataclass(frozen=True, slots=True)
class RangeSample:
    """One valid RANGE measurement in SI units and its original key."""

    key: SignalKey
    epoch: float
    code_m: float
    phase_m: float
    rate_mps: float
    code_std_m: float
    phase_std_m: float
    cn0_db_hz: float
    lock_seconds: float


def bdt_week_to_gps_seconds(week: int, seconds_of_week: float) -> float:
    """Convert a continuous BDT week and seconds to nominal GPST seconds.

    BDT week zero starts in GPS week 1356 and is nominally 14 seconds behind
    GPST. This does not apply sub-microsecond system-time corrections.
    """
    if type(week) is not int or not 0 <= week <= 65535:
        raise ValueError("BDT week must be an integer in 0..65535")
    if (
        isinstance(seconds_of_week, bool)
        or not math.isfinite(seconds_of_week)
        or not 0 <= seconds_of_week < 604800
    ):
        raise ValueError("BDT seconds outside week range")
    return (week + 1356) * 604800.0 + seconds_of_week + 14.0


def gps_epoch(
    message: Message, *, week_scale: Literal["GPST", "BDT"] | None = None
) -> float:
    """Return absolute GPST seconds from a receiver data-frame header.

    N4 ASCII GPS headers and binary reference 0 have been observed as GPST.
    R1.15 does not specify how non-GPS header weeks are numbered. For those
    headers, supply an independently verified ``week_scale`` explicitly. BDT
    means a continuous BDT week number and BDT seconds, not GPS-numbered weeks.
    Legacy headers are assumed GPST unless the caller specifies otherwise.
    """
    if week_scale not in (None, "GPST", "BDT"):
        raise ValueError("week_scale must be GPST or BDT")
    if not isinstance(message, (AsciiMessage, BinaryMessage)):
        raise ValueError("message carries no receiver timestamp")
    header = message.header
    if isinstance(header, (AsciiHeader, BinaryHeader)):
        if week_scale is None:
            gps_reference = (
                isinstance(header, AsciiHeader) and header.time_reference == "GPS"
            ) or (isinstance(header, BinaryHeader) and header.time_reference == 0)
            if not gps_reference:
                raise ValueError(
                    "non-GPS or unknown time reference, so specify a verified "
                    "week_scale"
                )
        week, seconds = header.week, header.milliseconds / 1000.0
    elif isinstance(header, LegacyBinaryHeader):
        if len(header.raw) < 20:
            raise ValueError("incomplete legacy receiver timestamp")
        week = int.from_bytes(header.raw[14:16], "little")
        seconds = int.from_bytes(header.raw[16:20], "little") / 1000.0
    elif isinstance(header, LegacyAsciiHeader):
        try:
            week, seconds = int(header.fields[4]), float(header.fields[5])
        except (IndexError, ValueError) as error:
            raise ValueError("invalid legacy receiver timestamp") from error
    else:
        raise ValueError("message carries no receiver timestamp")
    if (
        not 0 <= week <= 65535
        or not math.isfinite(seconds)
        or not 0 <= seconds < 604800
    ):
        raise ValueError("receiver timestamp outside week range")
    if week_scale == "BDT":
        return bdt_week_to_gps_seconds(week, seconds)
    return week * 604800.0 + seconds


def range_samples(
    record: Record, *, epoch: float | None = None
) -> tuple[RangeSample, ...]:
    """Select locked GPS signals and negate RANGE ADR into carrier metres."""
    return gnss_range_samples(record, epoch=epoch, systems=(0,), signals=(0, 14))


def gnss_range_samples(
    record: Record,
    *,
    epoch: float | None = None,
    systems: tuple[int, ...] | None = None,
    signals: tuple[int, ...] | None = None,
    glonass_channels: Mapping[int, int] | None = None,
) -> tuple[RangeSample, ...]:
    """Convert known GNSS carriers to range-increasing SI and omit unknown ones."""
    if epoch is None:
        if record.message is None:
            raise ValueError("RANGE record carries no receiver timestamp")
        epoch = gps_epoch(record.message)
    if not math.isfinite(epoch):
        raise ValueError("epoch must be finite")
    selected: dict[SignalKey, RangeSample] = {}
    for observation in record.records("observations"):
        status = observation.integer("tracking_status")
        key = SignalKey(
            (status >> 16) & 7, observation.integer("prn"), (status >> 21) & 31
        )
        channel = None
        if key.system == 1 and key.signal in (0, 5):
            # GLONASS uses frequency channels whose wire values are biased by seven.
            if glonass_channels is not None and key.prn in glonass_channels:
                channel = glonass_channels[key.prn]
            else:
                channel = observation.integer("frequency_channel") - 7
            if not -7 <= channel <= 6:
                continue
        signal = tracking_signal(
            status,
            glonass_channel=channel,
        )
        if (
            signal is None
            or signal.frequency_hz is None
            or (systems is not None and key.system not in systems)
            or (signals is not None and key.signal not in signals)
            or status & 0x1400 != 0x1400
        ):
            continue
        carrier = signal.frequency_hz
        scale = SPEED_OF_LIGHT / carrier
        # RANGE phase and Doppler use the opposite sign to increasing range.
        sample = RangeSample(
            key,
            epoch,
            observation.real("pseudorange"),
            -scale * observation.real("carrier_phase"),
            -scale * observation.real("doppler"),
            observation.real("pseudorange_std"),
            scale * observation.real("carrier_phase_std"),
            observation.real("cn0"),
            observation.real("lock_time"),
        )
        values = (
            sample.code_m,
            sample.phase_m,
            sample.rate_mps,
            sample.code_std_m,
            sample.phase_std_m,
            sample.cn0_db_hz,
            sample.lock_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            continue
        if (
            sample.code_m <= 0
            or sample.code_std_m <= 0
            or sample.phase_std_m <= 0
            or sample.lock_seconds <= 0
        ):
            continue
        previous = selected.get(key)
        # Retain the strongest observation when a signal appears more than once.
        if previous is None or sample.cn0_db_hz > previous.cn0_db_hz:
            selected[key] = sample
    return tuple(selected[key] for key in sorted(selected))


def sample_series(
    records: Sequence[Record],
) -> dict[SignalKey, tuple[RangeSample, ...]]:
    """Group GPS measurements while rejecting unordered or duplicate epochs."""
    series: dict[SignalKey, list[RangeSample]] = defaultdict(list)
    for record in records:
        for sample in range_samples(record):
            previous = series[sample.key]
            if previous and sample.epoch <= previous[-1].epoch:
                raise ValueError("RANGE epochs must increase strictly for each signal")
            previous.append(sample)
    return {key: tuple(values) for key, values in sorted(series.items())}
