"""Per-channel DSP tracking RAM for UM982 receivers."""

from dataclasses import dataclass
from math import isfinite
from struct import unpack_from
from typing import TYPE_CHECKING

from um982py.experimental.inav_pages import TRACKING_MEMORY_BASE, TRACKING_MEMORY_LENGTH
from um982py.geodesy import wavelength
from um982py.gnss import (
    DAY_SECONDS,
    F_B1I,
    F_B3I,
    F_E5B,
    F_E6,
    F_G1,
    F_G1_STEP,
    F_G2,
    F_G2_STEP,
    F_L1,
    F_L2,
    F_L5,
    WEEK_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from um982py.experimental.boot_memory import BootMemoryReader

__all__ = [
    "DSP_TRACKING_CLOCK_REFERENCE_WINDOW",
    "DSP_TRACKING_MEMORY_WINDOWS",
    "DspDopplerCalibration",
    "DspTrackingChannel",
    "DspTrackingObservation",
    "extract_dsp_tracking",
    "read_dsp_tracking",
]

_CHANNELS_PER_POSITION = 157
_FREQUENCY_POSITIONS = 7
_CHANNEL_COUNT = _CHANNELS_PER_POSITION * _FREQUENCY_POSITIONS
_CHANNEL_TABLE = 0x42BCB4
_MEASUREMENT_TABLE = 0x331DF8
_MEASUREMENT_TABLE_STRIDE = 0x1C
_MEASUREMENT_SIZE = 0x7E
_RF_TABLE = 0x402520
_RF_STRIDE = 0x50
_RF_COUNT = 22
_OBSERVATION_SIZE = 0xDC
_PHASE_TRACKED_FLAG = 0x10
_NATIVE_TIME_SCALES = {
    0x00: "GPST",
    0x08: "GPST",
    0x10: "GPST",
    0x03: "GST",
    0x13: "GST",
    0x1B: "GST",
    0x43: "GST",
    0x12: "BDT",
    0x22: "BDT",
    0x2A: "BDT",
    0x34: "GLOT",
    0x3C: "GLOT",
}
_SIGNAL_LAYOUTS = {
    0x00: ("GPS", "L1", F_L1, 0),
    0x08: ("GPS", "L2", F_L2, 0),
    0x10: ("GPS", "L5", F_L5, 0),
    0x03: ("GALILEO", "E1", F_L1, 100),
    0x13: ("GALILEO", "E5a", F_L5, 100),
    0x1B: ("GALILEO", "E5b", F_E5B, 100),
    0x43: ("GALILEO", "E6", F_E6, 100),
    0x12: ("BEIDOU", "B2a", F_L5, 160),
    0x22: ("BEIDOU", "B1I", F_B1I, 160),
    0x2A: ("BEIDOU", "B3", F_B3I, 160),
    0x34: ("GLONASS", "G1", F_G1, 64),
    0x3C: ("GLONASS", "G2", F_G2, 64),
}
_GLONASS_SPACING_HZ = {0x34: F_G1_STEP, 0x3C: F_G2_STEP}
_ALIGNED_WINDOW_ADDRESSES = range(
    TRACKING_MEMORY_BASE, TRACKING_MEMORY_BASE + TRACKING_MEMORY_LENGTH, 4
)

DSP_TRACKING_MEMORY_WINDOWS = (
    ("tracking", TRACKING_MEMORY_BASE, TRACKING_MEMORY_LENGTH),
    ("channels", _CHANNEL_TABLE, 4 * _CHANNEL_COUNT),
    ("rf_calibration", _RF_TABLE, _RF_STRIDE * _RF_COUNT),
)
"""Memory windows available for DSP tracking capture."""

DSP_TRACKING_CLOCK_REFERENCE_WINDOW = ("clock_reference", 0x13D442E0, 0x10)
"""Optional window holding the DSP clock reference used by output formatting."""


@dataclass(frozen=True, slots=True)
class DspDopplerCalibration:
    """Conversion from carrier tuning words for one DSP RF index."""

    reference_word: int
    hz_per_count: float

    @property
    def effective_sample_clock_hz(self) -> float:
        """Effective clock used by the carrier tuning accumulator."""
        return self.hz_per_count * 2**32


@dataclass(frozen=True, slots=True)
class DspTrackingObservation:
    """Values retained in the DSP's per-channel observation record."""

    address: int
    tracker_flags: int
    pseudorange_m: float | None
    """Last stored pseudorange, which can precede the snapshot."""
    carrier_phase_cycles: float | None
    """Carrier phase in the DSP's sign convention, gated by its tracking flag."""
    phase_reference_cycles: float | None
    """The carrier-phase reference stored separately by the DSP."""
    epoch_counter: int | None
    """Internal observation sequence counter within the receiver session."""
    gps_tow_ms: int | None
    """GPS time of week of the stored measurement, without the GPS week."""
    pseudorange_std_m: float | None = None
    """Receiver's code uncertainty model before application formatting."""
    carrier_phase_std_cycles: float | None = None
    """Receiver's phase uncertainty model before application formatting."""
    doppler_hz: float | None = None
    """Doppler stored with the observation at its measurement epoch."""
    phase_lock_ms: int | None = None
    """Internal phase lock counter before output-side adjustments."""
    native_time_s: float | None = None
    """High-resolution time tag in the native signal time scale."""
    native_time_scale: str | None = None
    """GPST, GST, BDT seconds-of-week, or GLOT seconds-of-day."""
    clock_correction_s: float | None = None
    """Output-side clock correction derived from tracker offset 0x90."""
    range_correction_m: float | None = None
    """Pseudorange correction applied by the receiver's output formatter."""

    @property
    def phase_offset_cycles(self) -> float | None:
        """Stored carrier phase relative to the DSP's phase reference."""
        if self.carrier_phase_cycles is None or self.phase_reference_cycles is None:
            return None
        return self.carrier_phase_cycles - self.phase_reference_cycles


@dataclass(frozen=True, slots=True)
class DspTrackingChannel:
    """One active channel's measurement record from the DSP debug path."""

    channel: int
    signal_family: int
    svid: int
    """ID printed by the DSP. For GLONASS this encodes FDMA channel plus eight."""
    tracking_svid: int
    """Raw satellite ID from the independent tracking record."""
    rf_index: int
    state: int
    tracking_status: int
    cn0_dbhz: float
    lock_count: int
    carrier_word: int
    """Signed 32-bit carrier tuning word."""
    calibration: DspDopplerCalibration | None
    address: int
    raw: bytes
    """Raw bytes of the receiver's measurement record."""
    observation: DspTrackingObservation | None = None
    """Observation state, if its full record is present in the RAM windows."""
    satellite_id: int | None = None
    """PRN for CDMA signals, or receiver PRN (slot plus 64) for GLONASS."""

    @property
    def constellation(self) -> str:
        """Constellation of the decoded DSP signal family."""
        return _SIGNAL_LAYOUTS[self.signal_family][0]

    @property
    def band(self) -> str:
        """Carrier band of the decoded DSP signal family."""
        return _SIGNAL_LAYOUTS[self.signal_family][1]

    @property
    def glonass_frequency_channel(self) -> int | None:
        return self.svid - 8 if self.signal_family in _GLONASS_SPACING_HZ else None

    @property
    def frequency_hz(self) -> float:
        """Carrier frequency, with the satellite-specific GLONASS FDMA offset."""
        center = _SIGNAL_LAYOUTS[self.signal_family][2]
        spacing = _GLONASS_SPACING_HZ.get(self.signal_family, 0)
        return center + (self.svid - 8) * spacing

    @property
    def wavelength_m(self) -> float:
        """Carrier wavelength in metres."""
        return wavelength(self.frequency_hz)

    @property
    def doppler_hz(self) -> float | None:
        """DSP Doppler before integer formatting, if RF calibration was available."""
        if self.calibration is None:
            return None
        reference = self.calibration.reference_word
        # The carrier difference is a signed 32-bit value that wraps around.
        delta = (self.carrier_word - reference + 2**31) % 2**32 - 2**31
        correction = (8 - self.svid) * _GLONASS_SPACING_HZ.get(self.signal_family, 0)
        doppler = delta * self.calibration.hz_per_count + correction
        return doppler if isfinite(doppler) else None

    @property
    def diagnostic_words(self) -> tuple[int, ...]:
        """Six diagnostic words retained in the measurement record."""
        return tuple(
            unpack_from("<I", self.raw, offset)[0]
            for offset in (0x2C, 0x34, 0x38, 0x20, 0x24, 0x28)
        )

    @property
    def normalized_accumulator(self) -> float | None:
        """Normalization of the fixed-point accumulator, in DSP units."""
        if self.lock_count == 0:
            return None
        # The normalization combines a whole-word count with a 32-bit
        # fractional word.
        high, _, low = unpack_from("<3I", self.raw, 0x20)
        return 81840 * (int(high) + int(low) / 2**32) / self.lock_count


def _decode_calibration(data: memoryview | None) -> DspDopplerCalibration | None:
    if data is None:
        return None
    scale = unpack_from("<d", data, 0x08)[0]
    if scale <= 0 or not isfinite(scale):
        return None
    return DspDopplerCalibration(unpack_from("<i", data, 0x18)[0], scale)


def _decode_observation(
    address: int,
    record: memoryview,
    signal_family: int,
    clock_reference: float | None = None,
) -> DspTrackingObservation:
    # The stored phase reference and carrier phase share a sign convention.
    flags = int(unpack_from("<H", record, 0x0A)[0])
    pseudorange, phase = unpack_from("<2d", record, 0x10)
    doppler = unpack_from("<f", record, 0x20)[0]
    code_std, phase_std = unpack_from("<2f", record, 0x30)
    phase_reference = unpack_from("<d", record, 0x48)[0]
    counter, tow_ms = unpack_from("<2I", record, 0xD4)
    native_time = unpack_from("<d", record, 0x88)[0]
    raw_clock = unpack_from("<f", record, 0x90)[0]
    reference = clock_reference
    valid_clock = reference is not None and isfinite(reference)
    clock_correction = (
        raw_clock - reference
        if reference is not None and valid_clock and isfinite(raw_clock)
        else None
    )
    time_limit = DAY_SECONDS if signal_family in _GLONASS_SPACING_HZ else WEEK_SECONDS
    has_native_time = isfinite(native_time) and 0 <= native_time < time_limit
    has_epoch = bool(counter or tow_ms) and tow_ms < WEEK_SECONDS * 1000
    has_range = isfinite(pseudorange) and pseudorange > 0
    has_phase = bool(flags & _PHASE_TRACKED_FLAG) and isfinite(phase)
    return DspTrackingObservation(
        address=address,
        tracker_flags=flags,
        pseudorange_m=pseudorange if has_range else None,
        carrier_phase_cycles=phase if has_phase else None,
        phase_reference_cycles=(
            phase_reference if phase_reference and isfinite(phase_reference) else None
        ),
        epoch_counter=counter if has_epoch else None,
        gps_tow_ms=tow_ms if has_epoch else None,
        pseudorange_std_m=code_std
        if has_range and isfinite(code_std) and code_std > 0
        else None,
        carrier_phase_std_cycles=phase_std
        if has_phase and isfinite(phase_std) and phase_std > 0
        else None,
        doppler_hz=doppler if has_epoch and isfinite(doppler) else None,
        phase_lock_ms=unpack_from("<I", record, 0xC4)[0] if has_phase else None,
        native_time_s=native_time if has_native_time else None,
        native_time_scale=(
            _NATIVE_TIME_SCALES[signal_family] if has_native_time else None
        ),
        clock_correction_s=clock_correction,
        range_correction_m=(
            8.0 * clock_correction if clock_correction is not None else None
        ),
    )


def extract_dsp_tracking(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[DspTrackingChannel, ...]:
    """Read active channels using the channel and measurement tables.

    Supply RAM windows with their base addresses from one capture. Channel
    measurements
    require both pointer tables and the referenced records. The RF calibration
    window is optional. This follows the frequency positions in measurement bank zero.
    """
    windows = tuple((base, memoryview(data)) for base, data in regions.values())
    clock_reference: float | None = None
    for base, data in windows:
        offset = 0x13D442E8 - base
        if 0 <= offset <= len(data) - 8:
            value = unpack_from("<d", data, offset)[0]
            if isfinite(value):
                clock_reference = value

    def read(address: int, size: int) -> memoryview | None:
        for base, data in windows:
            start = address - base
            if 0 <= start <= len(data) - size:
                return data[start : start + size]
        return None

    result = []
    for index in range(_CHANNEL_COUNT):
        position, group_index = divmod(index, _CHANNELS_PER_POSITION)
        measurement_entry = read(
            _MEASUREMENT_TABLE + group_index * _MEASUREMENT_TABLE_STRIDE + position * 4,
            4,
        )
        channel_entry = read(_CHANNEL_TABLE + index * 4, 4)
        if measurement_entry is None or channel_entry is None:
            continue
        address = unpack_from("<I", measurement_entry)[0]
        tracker_address = unpack_from("<I", channel_entry)[0]
        if (
            address not in _ALIGNED_WINDOW_ADDRESSES
            or tracker_address not in _ALIGNED_WINDOW_ADDRESSES
        ):
            continue
        row = read(address, _MEASUREMENT_SIZE)
        tracker = read(tracker_address, 12)
        if row is None or tracker is None:
            continue
        family, svid, state = row[:3]
        if family not in _SIGNAL_LAYOUTS or family != tracker[0] or svid == 0:
            continue
        channel, flags = unpack_from("<I2xH", tracker, 4)
        status = unpack_from("<I", row, 0x1C)[0]
        if channel != index + 1 or flags & 1 == 0 or status == 0:
            continue
        bias = _SIGNAL_LAYOUTS[family][3]
        tracking_svid = tracker[1]
        if svid != tracking_svid - bias:
            continue
        satellite_id: int | None = svid
        if family in _GLONASS_SPACING_HZ:
            if svid > 14:
                continue
            wire_prn = unpack_from("<H", tracker, 2)[0]
            satellite_id = wire_prn if 65 <= wire_prn <= 88 else None
        rf_index = row[9]
        calibration = None
        if rf_index < _RF_COUNT:
            calibration = _decode_calibration(
                read(_RF_TABLE + rf_index * _RF_STRIDE, 0x1C)
            )
        observation = read(tracker_address, _OBSERVATION_SIZE)
        result.append(
            DspTrackingChannel(
                channel=channel,
                signal_family=family,
                svid=svid,
                tracking_svid=tracking_svid,
                rf_index=rf_index,
                state=state,
                tracking_status=status,
                cn0_dbhz=unpack_from("<h", row, 0x0E)[0] / 100,
                lock_count=unpack_from("<H", row, 0x12)[0],
                carrier_word=unpack_from("<i", row, 0x30)[0],
                calibration=calibration,
                address=address,
                raw=bytes(row),
                observation=(
                    _decode_observation(
                        tracker_address, observation, family, clock_reference
                    )
                    if observation is not None
                    else None
                ),
                satellite_id=satellite_id,
            )
        )
    return tuple(result)


def read_dsp_tracking(reader: BootMemoryReader) -> tuple[DspTrackingChannel, ...]:
    """Read and decode DSP tracking windows with an open boot-memory reader."""
    return extract_dsp_tracking(
        {
            name: (base, reader.read_range(base, length))
            for name, base, length in DSP_TRACKING_MEMORY_WINDOWS
        }
    )
