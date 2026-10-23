"""Experimental broadcast orbit propagation for four constellations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from um982py.geodesy import SPEED_OF_LIGHT, geodetic_from_ecef, receiver_ecef
from um982py.geodesy import WGS84_A as WGS84_SEMI_MAJOR

if TYPE_CHECKING:
    from um982py.messages.record import Record

MU = 3.986005e14
EARTH_ROTATION_RATE = 7.2921151467e-5
J2 = 1.0826257e-3
WEEK_SECONDS = 604_800.0

__all__ = [
    "EARTH_ROTATION_RATE",
    "MU",
    "SPEED_OF_LIGHT",
    "WGS84_SEMI_MAJOR",
    "GlonassElements",
    "KeplerElements",
    "SatelliteState",
    "az_elevation_from_record",
    "azimuth_elevation",
    "clock_correction",
    "glonass_state",
    "orbit_state",
    "receiver_ecef",
    "solve_kepler",
    "state_from_record",
]


@dataclass(frozen=True, slots=True)
class KeplerElements:
    """Keplerian broadcast elements shared by GPS, BDS and Galileo."""

    semi_major_axis: float
    eccentricity: float
    mean_anomaly: float
    argument_of_perigee: float
    inclination: float
    right_ascension: float
    delta_n: float
    idot: float
    omega_dot: float
    cuc: float
    cus: float
    crc: float
    crs: float
    cic: float
    cis: float
    toe: float
    af0: float = 0.0
    af1: float = 0.0
    af2: float = 0.0
    tgd: float = 0.0
    toc: float | None = None

    @classmethod
    def from_record(cls, record: Record) -> KeplerElements:
        """Build elements from a GPS, BDS or Galileo ephemeris record."""
        axis = record.real("a") if "a" in record else record.real("roota") ** 2
        return cls(
            semi_major_axis=axis,
            eccentricity=record.real("ecc"),
            mean_anomaly=record.real("m0"),
            argument_of_perigee=record.real("omega"),
            inclination=record.real("i0"),
            right_ascension=_first(record, "omega_0", "omega0"),
            delta_n=_first(record, "delta_n", "deltan"),
            idot=record.real("idot"),
            omega_dot=_first(record, "omega_dot", "omegadot"),
            cuc=record.real("cuc"),
            cus=record.real("cus"),
            crc=record.real("crc"),
            crs=record.real("crs"),
            cic=record.real("cic"),
            cis=record.real("cis"),
            toe=record.real("toe"),
            af0=_first(record, "af0", "fnavaf0", "inavaf0"),
            af1=_first(record, "af1", "fnavaf1", "inavaf1"),
            af2=_first(record, "af2", "fnavaf2", "inavaf2"),
            tgd=_first(record, "tgd", "tgd1", "e1e5abgd"),
            toc=record.real("toc") if "toc" in record else None,
        )


@dataclass(frozen=True, slots=True)
class SatelliteState:
    """Satellite position and clock state at one instant."""

    x: float
    y: float
    z: float
    clock_bias: float
    radius: float


def _first(record: Record, *names: str, default: float = 0.0) -> float:
    """First present field among ``names``, or ``default``."""
    for name in names:
        if name in record:
            return record.real(name)
    return default


def solve_kepler(
    mean_anomaly: float, eccentricity: float, tolerance: float = 1e-13
) -> float:
    """Eccentric anomaly from Kepler's equation by fixed-point iteration."""
    if not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be in 0..1")
    anomaly = mean_anomaly
    for _ in range(64):
        step = (anomaly - eccentricity * math.sin(anomaly) - mean_anomaly) / (
            1 - eccentricity * math.cos(anomaly)
        )
        anomaly -= step
        if abs(step) < tolerance:
            return anomaly
    raise ValueError("Kepler iteration did not converge")


def orbit_state(
    elements: KeplerElements,
    time_of_flight: float,
    *,
    earth_rate: float = EARTH_ROTATION_RATE,
) -> SatelliteState:
    """Propagate Keplerian elements to an ECEF position and clock bias."""
    axis = elements.semi_major_axis
    if axis <= 0:
        raise ValueError("semi-major axis must be positive")
    time_of_flight = (
        time_of_flight + WEEK_SECONDS / 2
    ) % WEEK_SECONDS - WEEK_SECONDS / 2
    mean_motion = math.sqrt(MU / axis**3) + elements.delta_n
    mean_anomaly = elements.mean_anomaly + mean_motion * time_of_flight
    eccentric_anomaly = solve_kepler(mean_anomaly, elements.eccentricity)
    sin_e, cos_e = math.sin(eccentric_anomaly), math.cos(eccentric_anomaly)
    true_anomaly = math.atan2(
        math.sqrt(1 - elements.eccentricity**2) * sin_e,
        cos_e - elements.eccentricity,
    )
    latitude = true_anomaly + elements.argument_of_perigee
    twice_latitude = 2 * latitude
    argument_correction = elements.cus * math.sin(
        twice_latitude
    ) + elements.cuc * math.cos(twice_latitude)
    radius_correction = elements.crs * math.sin(
        twice_latitude
    ) + elements.crc * math.cos(twice_latitude)
    inclination_correction = elements.cis * math.sin(
        twice_latitude
    ) + elements.cic * math.cos(twice_latitude)
    corrected_latitude = latitude + argument_correction
    radius = axis * (1 - elements.eccentricity * cos_e) + radius_correction
    inclination = (
        elements.inclination + elements.idot * time_of_flight + inclination_correction
    )
    ascending_node = (
        elements.right_ascension
        + (elements.omega_dot - earth_rate) * time_of_flight
        - earth_rate * elements.toe
    )
    orbital_x = radius * math.cos(corrected_latitude)
    orbital_y = radius * math.sin(corrected_latitude)
    cos_node, sin_node = math.cos(ascending_node), math.sin(ascending_node)
    cos_inclination = math.cos(inclination)
    x = orbital_x * cos_node - orbital_y * cos_inclination * sin_node
    y = orbital_x * sin_node + orbital_y * cos_inclination * cos_node
    z = orbital_y * math.sin(inclination)
    return SatelliteState(
        x=x,
        y=y,
        z=z,
        clock_bias=clock_correction(elements, time_of_flight, eccentric_anomaly),
        radius=math.sqrt(x * x + y * y + z * z),
    )


def clock_correction(
    elements: KeplerElements, time_of_flight: float, eccentric_anomaly: float
) -> float:
    """Satellite clock bias in seconds including the relativistic term."""
    relativistic = -2 * math.sqrt(MU * elements.semi_major_axis) / SPEED_OF_LIGHT**2
    clock_time = (
        time_of_flight
        + elements.toe
        - (elements.toe if elements.toc is None else elements.toc)
    )
    clock_time = (clock_time + WEEK_SECONDS / 2) % WEEK_SECONDS - WEEK_SECONDS / 2
    return (
        elements.af0
        + elements.af1 * clock_time
        + elements.af2 * clock_time**2
        + relativistic * elements.eccentricity * math.sin(eccentric_anomaly)
        - elements.tgd
    )


def azimuth_elevation(
    state: SatelliteState, observer: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Azimuth, elevation in degrees and slant range in metres."""
    delta = (
        state.x - observer[0],
        state.y - observer[1],
        state.z - observer[2],
    )
    east = (
        -math.sin(_longitude(observer)) * delta[0]
        + math.cos(_longitude(observer)) * delta[1]
    )
    north = (
        -math.sin(_latitude(observer)) * math.cos(_longitude(observer)) * delta[0]
        - math.sin(_latitude(observer)) * math.sin(_longitude(observer)) * delta[1]
        + math.cos(_latitude(observer)) * delta[2]
    )
    up = (
        math.cos(_latitude(observer)) * math.cos(_longitude(observer)) * delta[0]
        + math.cos(_latitude(observer)) * math.sin(_longitude(observer)) * delta[1]
        + math.sin(_latitude(observer)) * delta[2]
    )
    horizontal = math.hypot(east, north)
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    elevation = math.degrees(math.atan2(up, horizontal))
    return azimuth, elevation, math.sqrt(sum(component**2 for component in delta))


def _latitude(observer: tuple[float, float, float]) -> float:
    return math.radians(geodetic_from_ecef(*observer)[0])


def _longitude(observer: tuple[float, float, float]) -> float:
    return math.atan2(observer[1], observer[0])


@dataclass(frozen=True, slots=True)
class GlonassElements:
    """PZ-90 state vector from a GLONASS ephemeris record."""

    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    ax: float
    ay: float
    az: float
    toe: float
    tau_n: float
    gamma_n: float

    @classmethod
    def from_record(cls, record: Record) -> GlonassElements:
        """Build a PZ-90 state from a decoded GLOEPH record."""
        return cls(
            x=record.real("pos_x"),
            y=record.real("pos_y"),
            z=record.real("pos_z"),
            vx=record.real("vel_x"),
            vy=record.real("vel_y"),
            vz=record.real("vel_z"),
            ax=record.real("ls_acc_x"),
            ay=record.real("ls_acc_y"),
            az=record.real("ls_acc_z"),
            toe=record.real("e_time"),
            tau_n=record.real("tau_n"),
            gamma_n=record.real("gamma"),
        )


def glonass_state(
    elements: GlonassElements, time_of_flight: float, step: float = 60.0
) -> SatelliteState:
    """Integrate the PZ-90 equations of motion from a GLONASS state vector."""
    state = [elements.x, elements.y, elements.z, elements.vx, elements.vy, elements.vz]
    if not math.isfinite(step) or step <= 0 or not math.isfinite(time_of_flight):
        raise ValueError("step must be positive and propagation time must be finite")
    remaining = time_of_flight
    while abs(remaining) > 1e-9:
        interval = math.copysign(min(step, abs(remaining)), remaining)
        state = _rk4(state, interval, (elements.ax, elements.ay, elements.az))
        remaining -= interval
    x, y, z = state[0], state[1], state[2]
    return SatelliteState(
        x=x,
        y=y,
        z=z,
        clock_bias=-elements.tau_n + elements.gamma_n * time_of_flight,
        radius=math.sqrt(x * x + y * y + z * z),
    )


def _acceleration(state: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = state[0], state[1], state[2]
    radius = math.sqrt(x * x + y * y + z * z)
    if radius <= 0:
        raise ValueError("GLONASS state has zero radius")
    mu = 3.9860044e14
    factor = 1.5 * J2 * mu * 6378136.0**2 / radius**5
    common = 5 * z * z / radius**2
    gravity = -mu / radius**3 - factor * (1 - common)
    omega = 7.292115e-5
    return (
        (gravity + omega**2) * x + 2 * omega * state[4],
        (gravity + omega**2) * y - 2 * omega * state[3],
        (gravity - 2 * factor) * z,
    )


def _rate(state: Sequence[float], external: Sequence[float]) -> list[float]:
    return [
        state[3],
        state[4],
        state[5],
        *[
            value + extra
            for value, extra in zip(_acceleration(state), external, strict=True)
        ],
    ]


def _rk4(state: Sequence[float], step: float, external: Sequence[float]) -> list[float]:
    k1 = _rate(state, external)
    k2 = _rate([v + step / 2 * k for v, k in zip(state, k1, strict=True)], external)
    k3 = _rate([v + step / 2 * k for v, k in zip(state, k2, strict=True)], external)
    k4 = _rate([v + step * k for v, k in zip(state, k3, strict=True)], external)
    return [
        v + step / 6 * (a + 2 * b + 2 * c + d)
        for v, a, b, c, d in zip(state, k1, k2, k3, k4, strict=True)
    ]


def state_from_record(
    record: Record, time_of_flight: float, *, earth_rate: float = EARTH_ROTATION_RATE
) -> SatelliteState:
    """Propagate any decoded ephemeris record to a position and clock state."""
    if "pos_x" in record:
        return glonass_state(GlonassElements.from_record(record), time_of_flight)
    return orbit_state(
        KeplerElements.from_record(record), time_of_flight, earth_rate=earth_rate
    )


def az_elevation_from_record(
    record: Record, observer: tuple[float, float, float], time_of_flight: float
) -> tuple[float, float, float]:
    """Azimuth, elevation and range of an ephemeris record from an observer."""
    return azimuth_elevation(state_from_record(record, time_of_flight), observer)
