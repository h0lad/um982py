"""Derives precipitable water vapour from the zenith wet delay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from um982py.commands import Log
from um982py.messages import Record, Value
from um982py.protocol import StreamDecoder

WATER_DENSITY_KG_PER_M3 = 1000.0
WATER_VAPOUR_GAS_CONSTANT_J_PER_KG_K = 461.5
REFRACTIVITY_K2_KELVIN_PER_HECTOPASCAL = 22.13
REFRACTIVITY_K3_KELVIN2_PER_HECTOPASCAL = 3.739e5
PASCALS_PER_HECTOPASCAL = 100.0
MILLIMETRES_PER_METRE = 1000.0

MANUAL_TROPINFO_LINE = (
    "#TROPINFOA,85,GPS,FINE,2244,93693000,0,0,18,63;"
    "SAASTAMOINEN,2.354103,2.292246,0.061857,0.026856,0.000000*89ed6541"
)

__all__ = [
    "BINARY_MODELS",
    "MANUAL_TROPINFO_LINE",
    "MILLIMETRES_PER_METRE",
    "PASCALS_PER_HECTOPASCAL",
    "REFRACTIVITY_K2_KELVIN_PER_HECTOPASCAL",
    "REFRACTIVITY_K3_KELVIN2_PER_HECTOPASCAL",
    "WATER_DENSITY_KG_PER_M3",
    "WATER_VAPOUR_GAS_CONSTANT_J_PER_KG_K",
    "Troposphere",
    "TroposphereModel",
    "WaterVapour",
    "manual_troposphere",
    "model_of",
    "pi_factor",
    "precipitable_water_millimetres",
    "tropinfo_record",
    "zwd_to_pwv_ratio",
]


class TroposphereModel(StrEnum):
    """Tropospheric model reported by TROPINFO."""

    SAASTAMOINEN = "SAASTAMOINEN"


BINARY_MODELS: Mapping[int, TroposphereModel] = MappingProxyType(
    {1: TroposphereModel.SAASTAMOINEN}
)


@dataclass(frozen=True, slots=True)
class Troposphere:
    """Zenith tropospheric delays of one TROPINFO record, in metres."""

    model: TroposphereModel
    zenith_total: float
    """Zenith total delay in metres."""
    dry: float
    """Zenith dry delay in metres."""
    wet: float
    """Zenith wet delay in metres."""
    std: float
    """Standard deviation of the zenith total delay in metres."""

    @classmethod
    def from_record(cls, record: Record) -> Troposphere:
        """Decode a TROPINFO record, accepting the binary model code."""
        return cls(
            model=model_of(record["trop_module"]),
            zenith_total=record.real("tropzenith"),
            dry=record.real("dry"),
            wet=record.real("wet"),
            std=record.real("std"),
        )

    @property
    def dry_plus_wet(self) -> float:
        """Zenith total delay rebuilt from the dry and wet components in metres."""
        return self.dry + self.wet


@dataclass(frozen=True, slots=True)
class WaterVapour:
    """Precipitable water vapour implied by one tropospheric delay record."""

    troposphere: Troposphere
    mean_temperature: float
    """Water vapour weighted mean temperature in kelvin."""

    @property
    def pi(self) -> float:
        """Bevis conversion factor from zenith wet delay to water vapour."""
        return pi_factor(self.mean_temperature)

    @property
    def zwd_to_pwv_ratio(self) -> float:
        """Zenith wet delay per unit of precipitable water vapour."""
        return zwd_to_pwv_ratio(self.mean_temperature)

    @property
    def millimetres(self) -> float:
        """Precipitable water vapour in millimetres."""
        return precipitable_water_millimetres(
            self.troposphere.wet, self.mean_temperature
        )


def pi_factor(mean_temperature: float) -> float:
    """Bevis et al. (1992) conversion factor from zenith wet delay to water vapour."""
    if mean_temperature <= 0:
        raise ValueError("mean temperature must be positive")
    k2 = REFRACTIVITY_K2_KELVIN_PER_HECTOPASCAL / PASCALS_PER_HECTOPASCAL
    k3 = REFRACTIVITY_K3_KELVIN2_PER_HECTOPASCAL / PASCALS_PER_HECTOPASCAL
    return 1e6 / (
        WATER_DENSITY_KG_PER_M3
        * WATER_VAPOUR_GAS_CONSTANT_J_PER_KG_K
        * (k3 / mean_temperature + k2)
    )


def zwd_to_pwv_ratio(mean_temperature: float) -> float:
    """Zenith wet delay per unit of precipitable water vapour."""
    return 1.0 / pi_factor(mean_temperature)


def precipitable_water_millimetres(
    zenith_wet_delay: float, mean_temperature: float
) -> float:
    """Precipitable water vapour in millimetres from a zenith wet delay in metres."""
    if zenith_wet_delay < 0:
        raise ValueError("zenith wet delay must not be negative")
    return pi_factor(mean_temperature) * zenith_wet_delay * MILLIMETRES_PER_METRE


def model_of(value: Value) -> TroposphereModel:
    """Tropospheric model of a TROPINFO model field in ASCII or binary form."""
    if isinstance(value, str):
        try:
            return TroposphereModel(value)
        except ValueError:
            raise ValueError(f"unknown tropospheric model {value}") from None
    if isinstance(value, int):
        try:
            return BINARY_MODELS[value]
        except KeyError:
            raise ValueError(f"unknown tropospheric model code {value}") from None
    raise ValueError("tropospheric model is neither a name nor a code")


def tropinfo_record(line: str) -> Record:
    """Decode one TROPINFO sentence from its wire text."""
    frames = StreamDecoder().feed(f"{line}\r\n".encode("ascii"))
    if not frames:
        raise ValueError("no complete frame in the troposphere line")
    return Log.TROPINFO.decode(frames[0])


def manual_troposphere() -> Troposphere:
    """The tropospheric delays of the interface guide's published TROPINFO example."""
    return Troposphere.from_record(tropinfo_record(MANUAL_TROPINFO_LINE))
