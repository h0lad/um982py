"""Broadcast ephemerides retained in UM982 DSP RAM."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from struct import unpack_from
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from um982py.experimental.boot_memory import BootMemoryReader

__all__ = [
    "DSP_EPHEMERIS_MEMORY_WINDOWS",
    "DSP_GLONASS_WORK_WINDOW",
    "DspGalileoEphemeris",
    "DspGlonassEphemeris",
    "DspGlonassWorkRecord",
    "DspKeplerEphemeris",
    "extract_dsp_ephemerides",
    "extract_dsp_glonass_work",
    "read_dsp_ephemeris_windows",
    "read_dsp_glonass_work_windows",
]

_KEPLER_TABLES = (
    ("gps_ephemeris", 0x13D729E8, 42, 0xC0, "GPS"),
    ("beidou_ephemeris", 0x13D50510, 63, 0xC0, "BEIDOU"),
)
_GALILEO_TABLE = ("galileo_ephemeris", 0x13D13418, 36, 0xF0)
_GLONASS_TABLE = ("glonass_ephemeris", 0x13D61B18, 32, 0x78)
DSP_GLONASS_WORK_WINDOW = ("glonass_work", 0x13D02600, 24 * 0x40)

DSP_EPHEMERIS_MEMORY_WINDOWS = (
    ("gps_ephemeris", 0x13D729E8, 42 * 0xC0),
    ("galileo_ephemeris", 0x13D13418, 36 * 0xF0),
    ("beidou_ephemeris", 0x13D50510, 63 * 0xC0),
    ("glonass_ephemeris", 0x13D61B18, 32 * 0x78),
    DSP_GLONASS_WORK_WINDOW,
)
"""Memory windows holding the receiver's broadcast ephemeris copies."""


@dataclass(frozen=True, slots=True)
class DspGlonassWorkRecord:
    """A GLONASS propagation work record written by the baseband receiver."""

    index: int
    reference_time_sod_s: int
    """Ephemeris reference time in GLOT seconds of day."""
    propagation_time_sod_s: float
    """Time to which this work record was propagated."""
    position_ecef_m: tuple[float, float, float]
    velocity_ecef_mps: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class DspKeplerEphemeris:
    """A GPS or BeiDou broadcast ephemeris in DSP RAM."""

    constellation: str
    satellite_id: int
    toe_s: int
    """Ephemeris reference time in native seconds of week."""
    sqrt_a: float
    """Square root of the semi-major axis."""
    delta_n: float
    mean_anomaly: float
    eccentricity: float
    argument_of_perigee: float
    cuc: float
    cus: float
    crc: float
    crs: float
    cic: float
    cis: float
    inclination: float
    idot: float
    ascending_node: float
    ascending_node_rate: float
    toc_s: int
    af0: float
    af1: float
    af2: float
    group_delay_s: float
    week_native: int | None = None
    """Week number in the constellation's native week scale."""
    iodc: int | None = None
    """GPS issue of data, clock."""
    aode: int | None = None
    """BeiDou issue of data, ephemeris."""
    aode_2: int | None = None
    """Second BeiDou issue-of-data field retained with the ephemeris."""

    @property
    def gps_week(self) -> int | None:
        """GPS week after applying the constellation's week offset."""
        if self.week_native is None:
            return None
        return self.week_native + {"GPS": 0, "BEIDOU": 1356}[self.constellation]

    @property
    def iode(self) -> int | None:
        """Issue of data, ephemeris, derived from the GPS IODC."""
        if self.iodc is None:
            return None
        return self.iodc & 0xFF


@dataclass(frozen=True, slots=True)
class DspGalileoEphemeris:
    """A Galileo broadcast ephemeris with both F/NAV and I/NAV clocks."""

    satellite_id: int
    toe_s: int
    sqrt_a: float
    delta_n: float
    mean_anomaly: float
    eccentricity: float
    argument_of_perigee: float
    cuc: float
    cus: float
    crc: float
    crs: float
    cic: float
    cis: float
    inclination: float
    idot: float
    ascending_node: float
    ascending_node_rate: float
    fnav_toc_s: int
    fnav_af0: float
    fnav_af1: float
    fnav_af2: float
    inav_toc_s: int
    inav_af0: float
    inav_af1: float
    inav_af2: float
    e1e5a_bgd_s: float
    e1e5b_bgd_s: float
    week_native: int | None = None
    """Galileo week number in Galileo's native week scale."""
    iodnav: int | None = None
    """Galileo issue of data, navigation."""

    @property
    def gps_week(self) -> int | None:
        """GPS week after adding the Galileo epoch offset."""
        if self.week_native is None:
            return None
        return self.week_native + 1024


@dataclass(frozen=True, slots=True)
class DspGlonassEphemeris:
    """A GLONASS PZ-90 state vector in DSP RAM."""

    satellite_id: int
    """Receiver slot copied from the application's GLONASS slot numbering."""
    e_time_sod_s: int
    """Reference time in GLOT seconds of day."""
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    ax: float
    ay: float
    az: float
    tau_n: float
    delta_tau_n: float
    gamma: float
    nt: int
    ft: int | None = None
    """GLONASS ephemeris flag retained in byte 4."""
    flags: int | None = None
    """GLONASS ephemeris flags retained in byte 2."""


def _record(
    regions: Mapping[str, bytes], name: str, index: int, stride: int
) -> bytes | None:
    raw = regions.get(name)
    if raw is None:
        return None
    if len(raw) == 0 or len(raw) % stride:
        return None
    start = index * stride
    return raw[start : start + stride] if start + stride <= len(raw) else None


def _kepler(
    constellation: str, satellite_id: int, rec: bytes
) -> DspKeplerEphemeris | None:
    toe = unpack_from("<I", rec, 0x08)[0]
    sqrt_a = unpack_from("<d", rec, 0x10)[0]
    if toe == 0 or not isfinite(sqrt_a) or sqrt_a <= 0:
        return None
    values = [unpack_from("<d", rec, offset)[0] for offset in range(0x18, 0x88, 8)]
    if not all(map(isfinite, values)):
        return None
    (
        delta_n,
        mean_anomaly,
        eccentricity,
        argument_of_perigee,
        cuc,
        cus,
        crc,
        crs,
        cic,
        cis,
        inclination,
        idot,
        ascending_node,
        ascending_node_rate,
    ) = values
    clock = [unpack_from("<d", rec, offset)[0] for offset in (0x98, 0xA0, 0xA8, 0xB0)]
    if not all(map(isfinite, clock)):
        return None
    af0, af1, af2, group_delay = clock
    return DspKeplerEphemeris(
        constellation=constellation,
        satellite_id=satellite_id,
        toe_s=toe,
        sqrt_a=sqrt_a,
        delta_n=delta_n,
        mean_anomaly=mean_anomaly,
        eccentricity=eccentricity,
        argument_of_perigee=argument_of_perigee,
        cuc=cuc,
        cus=cus,
        crc=crc,
        crs=crs,
        cic=cic,
        cis=cis,
        inclination=inclination,
        idot=idot,
        ascending_node=ascending_node,
        ascending_node_rate=ascending_node_rate,
        toc_s=unpack_from("<I", rec, 0x90)[0],
        af0=af0,
        af1=af1,
        af2=af2,
        group_delay_s=group_delay,
        week_native=unpack_from("<H", rec, 0x02)[0],
        iodc=unpack_from("<H", rec, 0xB8)[0] if constellation == "GPS" else None,
        aode=rec[0x06] if constellation == "BEIDOU" else None,
        aode_2=rec[0x07] if constellation == "BEIDOU" else None,
    )


def _galileo(satellite_id: int, rec: bytes) -> DspGalileoEphemeris | None:
    toe = unpack_from("<I", rec, 0x10)[0]
    sqrt_a = unpack_from("<d", rec, 0x18)[0]
    if toe == 0 or not isfinite(sqrt_a) or sqrt_a <= 0:
        return None
    values = [unpack_from("<d", rec, offset)[0] for offset in range(0x20, 0x90, 8)]
    if not all(map(isfinite, values)):
        return None
    (
        delta_n,
        mean_anomaly,
        eccentricity,
        argument_of_perigee,
        cuc,
        cus,
        crc,
        crs,
        cic,
        cis,
        inclination,
        idot,
        ascending_node,
        ascending_node_rate,
    ) = values
    clock = [
        unpack_from("<d", rec, offset)[0]
        for offset in (0xA0, 0xA8, 0xB0, 0xC0, 0xC8, 0xD0, 0xD8, 0xE0)
    ]
    if not all(map(isfinite, clock)):
        return None
    return DspGalileoEphemeris(
        satellite_id=satellite_id,
        toe_s=toe,
        sqrt_a=sqrt_a,
        delta_n=delta_n,
        mean_anomaly=mean_anomaly,
        eccentricity=eccentricity,
        argument_of_perigee=argument_of_perigee,
        cuc=cuc,
        cus=cus,
        crc=crc,
        crs=crs,
        cic=cic,
        cis=cis,
        inclination=inclination,
        idot=idot,
        ascending_node=ascending_node,
        ascending_node_rate=ascending_node_rate,
        fnav_toc_s=unpack_from("<I", rec, 0xB8)[0],
        fnav_af0=clock[3],
        fnav_af1=clock[4],
        fnav_af2=clock[5],
        inav_toc_s=unpack_from("<I", rec, 0x98)[0],
        inav_af0=clock[0],
        inav_af1=clock[1],
        inav_af2=clock[2],
        e1e5a_bgd_s=clock[6],
        e1e5b_bgd_s=clock[7],
        week_native=unpack_from("<H", rec, 0x02)[0],
        iodnav=rec[0x04] & 0x1F,
    )


def _glonass(satellite_id: int, rec: bytes) -> DspGlonassEphemeris | None:
    e_time = unpack_from("<I", rec, 0x68)[0]
    values = [unpack_from("<d", rec, offset)[0] for offset in range(0x08, 0x68, 8)]
    if e_time == 0 or not all(map(isfinite, values)):
        return None
    gamma, tau_n, delta_tau_n, x, y, z, vx, vy, vz, ax, ay, az = values
    if not 20e6 <= sqrt(x * x + y * y + z * z) <= 50e6:
        return None
    return DspGlonassEphemeris(
        satellite_id=satellite_id,
        e_time_sod_s=e_time,
        x=x,
        y=y,
        z=z,
        vx=vx,
        vy=vy,
        vz=vz,
        ax=ax,
        ay=ay,
        az=az,
        tau_n=tau_n,
        delta_tau_n=delta_tau_n,
        gamma=gamma,
        nt=unpack_from("<H", rec, 0x70)[0],
        ft=rec[0x04] & 0x07,
        flags=rec[0x02] & 0x0F,
    )


def read_dsp_ephemeris_windows(reader: BootMemoryReader) -> dict[str, bytes]:
    """Read the broadcast-ephemeris tables without exposing their addresses."""
    return {
        name: reader.read_range(address, length)
        for name, address, length in DSP_EPHEMERIS_MEMORY_WINDOWS
    }


def read_dsp_glonass_work_windows(reader: BootMemoryReader) -> dict[str, bytes]:
    """Read the GLONASS propagation work records."""
    name, address, length = DSP_GLONASS_WORK_WINDOW
    return {name: reader.read_range(address, length)}


def extract_dsp_glonass_work(
    regions: Mapping[str, bytes],
) -> tuple[DspGlonassWorkRecord, ...]:
    """Decode GLONASS propagation work records from captured DSP RAM.

    The reference time matches the GLONASS ephemeris issue time converted to
    GLOT seconds of day. The position and velocity fields are the work values
    written by the baseband propagation helpers.
    """
    raw = regions.get(DSP_GLONASS_WORK_WINDOW[0])
    if raw is None or len(raw) == 0 or len(raw) % 0x40:
        return ()
    result = []
    for index in range(min(len(raw) // 0x40, 24)):
        rec = raw[index * 0x40 : (index + 1) * 0x40]
        reference = unpack_from("<I", rec, 0x00)[0]
        values = [unpack_from("<d", rec, offset)[0] for offset in range(0x08, 0x40, 8)]
        if reference == 0 or not all(map(isfinite, values)):
            continue
        propagation_time, x, y, z, vx, vy, vz = values
        result.append(
            DspGlonassWorkRecord(
                index=index,
                reference_time_sod_s=reference,
                propagation_time_sod_s=propagation_time,
                position_ecef_m=(x, y, z),
                velocity_ecef_mps=(vx, vy, vz),
            )
        )
    return tuple(result)


def extract_dsp_ephemerides(
    regions: Mapping[str, bytes],
) -> tuple[DspKeplerEphemeris | DspGalileoEphemeris | DspGlonassEphemeris, ...]:
    """Decode the broadcast ephemerides retained in captured DSP windows.

    Kepler-element fields are in metres, seconds and radians. Galileo keeps
    both F/NAV and I/NAV clock sets. GLONASS state vectors are PZ-90 values and
    their reference time is GLOT seconds of day.
    """
    result: list[DspKeplerEphemeris | DspGalileoEphemeris | DspGlonassEphemeris] = []
    for name, _, count, stride, constellation in _KEPLER_TABLES:
        for index in range(count):
            rec = _record(regions, name, index, stride)
            if rec is None:
                break
            entry = _kepler(constellation, index + 1, rec)
            if entry is not None:
                result.append(entry)
    name, _, count, stride = _GALILEO_TABLE
    for index in range(count):
        rec = _record(regions, name, index, stride)
        if rec is None:
            break
        galileo_entry = _galileo(index + 1, rec)
        if galileo_entry is not None:
            result.append(galileo_entry)
    name, _, count, stride = _GLONASS_TABLE
    for index in range(count):
        rec = _record(regions, name, index, stride)
        if rec is None:
            break
        glonass_entry = _glonass(index + 38, rec)
        if glonass_entry is not None:
            result.append(glonass_entry)
    return tuple(result)
