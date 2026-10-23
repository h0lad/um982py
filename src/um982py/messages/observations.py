"""Tracking status and observation models."""

from dataclasses import dataclass
from typing import Self

from um982py.errors import ProtocolError
from um982py.messages.record import Record

PSR_STANDARD_DEVIATIONS = (
    0.050,
    0.075,
    0.113,
    0.169,
    0.253,
    0.380,
    0.570,
    0.854,
    1.281,
    2.375,
    4.750,
    9.500,
    19.000,
    38.000,
    76.000,
    152.000,
)


@dataclass(frozen=True, slots=True)
class TrackingStatus:
    raw: int

    @property
    def channel(self) -> int:
        return (self.raw >> 5) & 31

    @property
    def phase_valid(self) -> bool:
        return bool(self.raw & (1 << 10))

    @property
    def pseudorange_valid(self) -> bool:
        return bool(self.raw & (1 << 12))

    @property
    def system(self) -> int:
        return (self.raw >> 16) & 7

    @property
    def signal(self) -> int:
        return (self.raw >> 21) & 31

    @property
    def l2c(self) -> bool:
        return bool(self.raw & (1 << 26))


@dataclass(frozen=True, slots=True)
class Observation:
    prn: int
    glonass_frequency: int | None
    pseudorange_m: float
    carrier_phase_cycles: float
    pseudorange_std_m: float
    carrier_phase_std_cycles: float
    doppler_hz: float
    cn0_db_hz: float
    lock_seconds: float
    tracking: TrackingStatus
    phase_is_modulo: bool = False

    @classmethod
    def from_record(cls, record: Record) -> Self:
        data = record.get("cmp_record")
        if data is not None:
            if not isinstance(data, bytes) or len(data) != 24:
                raise ProtocolError("Expected 24-byte compressed observation")
            bits = int.from_bytes(data, "little")
            doppler = (bits >> 32) & ((1 << 28) - 1)
            if doppler & (1 << 27):
                doppler -= 1 << 28
            tracking = TrackingStatus(bits & 0xFFFFFFFF)
            return cls(
                (bits >> 136) & 255,
                ((bits >> 170) & 63) - 7 if tracking.system == 1 else None,
                ((bits >> 60) & ((1 << 36) - 1)) / 128,
                ((bits >> 96) & 0xFFFFFFFF) / 256,
                PSR_STANDARD_DEVIATIONS[(bits >> 128) & 15],
                (((bits >> 132) & 15) + 1) / 512,
                doppler / 256,
                20 + ((bits >> 165) & 31),
                ((bits >> 144) & ((1 << 21) - 1)) / 32,
                tracking,
                phase_is_modulo=True,
            )
        tracking = TrackingStatus(record.integer("ch_tr_status"))
        return cls(
            record.integer("prn_slot"),
            record.integer("system_freq") - 7 if tracking.system == 1 else None,
            record.real("psr"),
            record.real("adr"),
            record.real("psr_std") / 100,
            record.real("adr_std") / 10000,
            record.real("dopp"),
            record.real("c_n0") / 100,
            record.real("locktime"),
            tracking,
        )
