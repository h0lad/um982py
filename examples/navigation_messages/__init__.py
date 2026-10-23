"""Builds sky, orbit and table figures for every navigation message."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from examples.ephemeris_orbit import (
    EARTH_ROTATION_RATE,
    MU,
    GlonassElements,
    KeplerElements,
    azimuth_elevation,
    glonass_state,
    orbit_state,
)
from um982py.messages.record import Record

SKY_WIDTH = 640.0
SKY_HEIGHT = 680.0
SKY_CENTRE = (320.0, 300.0)
SKY_RADIUS = 260.0
SKY_MARKER_RADIUS = 4.0
ORBIT_WIDTH = 760.0
ORBIT_HEIGHT = 520.0
ORBIT_LEFT = 90.0
ORBIT_RIGHT = 40.0
ORBIT_TOP = 70.0
ORBIT_BOTTOM = 70.0
ORBIT_MAX_INCLINATION = 90.0
ORBIT_MIN_RADIUS = 20.0e6
ORBIT_MAX_RADIUS = 45.0e6
TABLE_WIDTH = 1560.0
TABLE_ROW_HEIGHT = 22.0
TABLE_TOP = 96.0
TABLE_COLUMNS = (40.0, 240.0, 400.0, 640.0, 860.0, 1060.0, 1300.0)
TABLE_HEADINGS = (
    "PRN",
    "constellation",
    "semi-major axis / km",
    "eccentricity",
    "inclination / deg",
    "radius / km",
    "clock bias / ns",
)

__all__ = [
    "COLOURS",
    "FAMILIES",
    "HIGH_ORBIT_MIN",
    "MEDIUM_ORBIT_MAX",
    "MEDIUM_ORBIT_MIN",
    "PREFIXES",
    "SKY_CENTRE",
    "SKY_RADIUS",
    "NavigationSatellite",
    "OrbitRegime",
    "SatelliteSystem",
    "figures",
    "kepler_elements",
    "marker_position",
    "navigation_satellite",
    "navigation_satellites",
    "orbit_plot",
    "orbital_elements",
    "polar_position",
    "satellite_csv",
    "satellite_number",
    "satellite_payload",
    "sky_plot",
    "table_plot",
    "time_of_flight",
]


class SatelliteSystem(StrEnum):
    """Constellation that broadcasts an ephemeris record."""

    GPS = "GPS"
    GALILEO = "GALILEO"
    BEIDOU = "BEIDOU"
    GLONASS = "GLONASS"


class OrbitRegime(StrEnum):
    """Geocentric orbit regime implied by the semi-major axis."""

    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    GLONASS = "GLONASS"


FAMILIES: Mapping[str, SatelliteSystem] = {
    "GPSEPH": SatelliteSystem.GPS,
    "GALEPH": SatelliteSystem.GALILEO,
    "BDSEPH": SatelliteSystem.BEIDOU,
    "GLOEPH": SatelliteSystem.GLONASS,
}

PREFIXES: Mapping[SatelliteSystem, str] = {
    SatelliteSystem.GPS: "G",
    SatelliteSystem.GALILEO: "E",
    SatelliteSystem.BEIDOU: "C",
    SatelliteSystem.GLONASS: "R",
}

COLOURS: Mapping[SatelliteSystem, str] = {
    SatelliteSystem.GPS: "#1f77b4",
    SatelliteSystem.GALILEO: "#2ca02c",
    SatelliteSystem.BEIDOU: "#9467bd",
    SatelliteSystem.GLONASS: "#d62728",
}

MEDIUM_ORBIT_MIN = 26.0e6
MEDIUM_ORBIT_MAX = 30.0e6
HIGH_ORBIT_MIN = 40.0e6


@dataclass(frozen=True, slots=True)
class NavigationSatellite:
    """Orbital elements, position and sky angle of one navigated satellite."""

    system: SatelliteSystem
    prn: int
    semi_major_axis: float
    eccentricity: float
    inclination: float
    radius: float
    clock_bias: float
    azimuth: float
    elevation: float

    @property
    def orbit_regime(self) -> OrbitRegime:
        """Orbit regime from the semi-major axis."""
        if self.system is SatelliteSystem.GLONASS:
            return OrbitRegime.GLONASS
        if self.semi_major_axis >= HIGH_ORBIT_MIN:
            return OrbitRegime.HIGH
        return OrbitRegime.MEDIUM

    @property
    def in_medium_band(self) -> bool:
        """Whether the semi-major axis lies in the 26 000..30 000 km MEO band."""
        return MEDIUM_ORBIT_MIN < self.semi_major_axis < MEDIUM_ORBIT_MAX


def kepler_elements(record: Record) -> KeplerElements:
    """Keplerian elements of a decoded GPS, BDS or Galileo ephemeris."""
    if "roota" in record:
        return _galileo_elements(record)
    return KeplerElements.from_record(record)


def _galileo_elements(record: Record) -> KeplerElements:
    clock = ("fnavaf0", "fnavaf1", "fnavaf2")
    if not _is_true(record["fnavreceived"]):
        clock = ("inavaf0", "inavaf1", "inavaf2")
    return KeplerElements(
        semi_major_axis=record.real("roota") ** 2,
        eccentricity=record.real("ecc"),
        mean_anomaly=record.real("m0"),
        argument_of_perigee=record.real("omega"),
        inclination=record.real("i0"),
        right_ascension=record.real("omega0"),
        delta_n=record.real("deltan"),
        idot=record.real("idot"),
        omega_dot=record.real("omegadot"),
        cuc=record.real("cuc"),
        cus=record.real("cus"),
        crc=record.real("crc"),
        crs=record.real("crs"),
        cic=record.real("cic"),
        cis=record.real("cis"),
        toe=record.real("toe"),
        af0=record.real(clock[0]),
        af1=record.real(clock[1]),
        af2=record.real(clock[2]),
        tgd=record.real("e1e5abgd"),
    )


def _is_true(value: object) -> bool:
    return value is True or value == "TRUE" or value == 1


def orbital_elements(
    position: tuple[float, float, float],
    velocity: tuple[float, float, float],
    *,
    earth_rate: float = EARTH_ROTATION_RATE,
) -> tuple[float, float, float]:
    """Semi-major axis, eccentricity and inclination of an Earth-fixed state."""
    radius = math.sqrt(sum(component**2 for component in position))
    inertial = (
        velocity[0] - earth_rate * position[1],
        velocity[1] + earth_rate * position[0],
        velocity[2],
    )
    speed_squared = sum(component**2 for component in inertial)
    semi_major_axis = 1.0 / (2.0 / radius - speed_squared / MU)
    dot = sum(p * v for p, v in zip(position, inertial, strict=True))
    vector = tuple(
        ((speed_squared - MU / radius) * p - dot * v) / MU
        for p, v in zip(position, inertial, strict=True)
    )
    momentum = (
        position[1] * inertial[2] - position[2] * inertial[1],
        position[2] * inertial[0] - position[0] * inertial[2],
        position[0] * inertial[1] - position[1] * inertial[0],
    )
    inclination = math.degrees(
        math.acos(momentum[2] / math.sqrt(sum(component**2 for component in momentum)))
    )
    return (
        semi_major_axis,
        math.sqrt(sum(component**2 for component in vector)),
        inclination,
    )


def satellite_number(record: Record) -> int:
    """Satellite number of a decoded ephemeris record."""
    for key in ("prn", "satid", "sloto"):
        if key in record:
            return record.integer(key)
    raise ValueError("ephemeris record has no satellite number")


def time_of_flight(record: Record, epoch: float) -> float:
    """Seconds between the broadcast epoch of the elements and ``epoch``."""
    if "e_time" in record:
        return epoch - record.real("e_time") / 1000.0
    return epoch - record.real("toe")


def navigation_satellite(
    system: SatelliteSystem,
    record: Record,
    observer: tuple[float, float, float],
    epoch: float,
) -> NavigationSatellite:
    """Propagate one ephemeris record to ``epoch`` and place it in the sky."""
    flight_time = time_of_flight(record, epoch)
    if system is SatelliteSystem.GLONASS:
        elements = GlonassElements.from_record(record)
        state = glonass_state(elements, flight_time)
        semi_major_axis, eccentricity, inclination = orbital_elements(
            (elements.x, elements.y, elements.z),
            (elements.vx, elements.vy, elements.vz),
        )
    else:
        kepler = kepler_elements(record)
        state = orbit_state(kepler, flight_time)
        semi_major_axis = kepler.semi_major_axis
        eccentricity = kepler.eccentricity
        inclination = math.degrees(kepler.inclination)
    azimuth, elevation, _ = azimuth_elevation(state, observer)
    return NavigationSatellite(
        system=system,
        prn=satellite_number(record),
        semi_major_axis=semi_major_axis,
        eccentricity=eccentricity,
        inclination=inclination,
        radius=state.radius,
        clock_bias=state.clock_bias,
        azimuth=azimuth,
        elevation=elevation,
    )


def navigation_satellites(
    records: Mapping[str, Sequence[Record]],
    observer: tuple[float, float, float],
    epoch: float,
) -> tuple[NavigationSatellite, ...]:
    """Every decoded satellite of every family, sorted by system and number."""
    satellites = [
        navigation_satellite(FAMILIES[name], record, observer, epoch)
        for name, family in records.items()
        for record in family
    ]
    return tuple(sorted(satellites, key=lambda item: (item.system.value, item.prn)))


def polar_position(
    azimuth: float,
    elevation: float,
    centre: tuple[float, float] = SKY_CENTRE,
    radius: float = SKY_RADIUS,
) -> tuple[float, float]:
    """Pixel position with the zenith at the centre and the horizon on the rim."""
    distance = radius * (90.0 - elevation) / 90.0
    angle = math.radians(azimuth)
    return (
        centre[0] + distance * math.sin(angle),
        centre[1] - distance * math.cos(angle),
    )


def marker_position(
    satellite: NavigationSatellite,
) -> tuple[float, float]:
    """Pixel position of a satellite in the sky plot."""
    return polar_position(satellite.azimuth, satellite.elevation)


def sky_plot(satellites: Sequence[NavigationSatellite]) -> str:
    """Polar azimuth and elevation figure with one marker per satellite."""
    centre_x, centre_y = SKY_CENTRE
    body = [
        _element(
            "circle",
            cx=_number(centre_x),
            cy=_number(centre_y),
            r=_number(SKY_RADIUS),
            fill="none",
            stroke="#999999",
            stroke_width="1.5",
        )
    ]
    body.extend(
        _element(
            "circle",
            cx=_number(centre_x),
            cy=_number(centre_y),
            r=_number(SKY_RADIUS * (90.0 - elevation) / 90.0),
            fill="none",
            stroke="#dddddd",
            stroke_width="1",
        )
        for elevation in (30.0, 60.0)
    )
    for azimuth, label in ((0.0, "N"), (90.0, "E"), (180.0, "S"), (270.0, "W")):
        rim_x, rim_y = polar_position(azimuth, 0.0)
        body.append(
            _element(
                "line",
                x1=_number(centre_x),
                y1=_number(centre_y),
                x2=_number(rim_x),
                y2=_number(rim_y),
                stroke="#dddddd",
                stroke_width="1",
            )
        )
        body.append(
            _element(
                "text",
                label,
                x=_number(polar_position(azimuth, -6.0)[0]),
                y=_number(polar_position(azimuth, -6.0)[1]),
                fill="#333333",
                font_size="16",
                text_anchor="middle",
            )
        )
    body.append(
        _element(
            "text",
            "azimuth clockwise from north, elevation from the rim to the zenith",
            x=_number(centre_x),
            y=_number(SKY_HEIGHT - 20.0),
            fill="#333333",
            font_size="14",
            text_anchor="middle",
        )
    )
    for satellite in satellites:
        marker_x, marker_y = marker_position(satellite)
        colour = COLOURS[satellite.system]
        body.append(
            _element(
                "g",
                _element(
                    "circle",
                    cx=_number(marker_x),
                    cy=_number(marker_y),
                    r=_number(SKY_MARKER_RADIUS),
                    fill=colour,
                    stroke="#ffffff",
                    stroke_width="0.5",
                    class_="marker",
                )
                + _element(
                    "text",
                    f"{PREFIXES[satellite.system]}{satellite.prn}",
                    x=_number(marker_x + 6.0),
                    y=_number(marker_y - 6.0),
                    fill=colour,
                    font_size="11",
                    text_anchor="start",
                ),
                class_="satellite",
                data_prn=str(satellite.prn),
                data_constellation=satellite.system.value,
            )
        )
    return _document(SKY_WIDTH, SKY_HEIGHT, [_title("sky plot"), *body])


def orbit_plot(satellites: Sequence[NavigationSatellite]) -> str:
    """Orbital radius against inclination, one point per satellite."""
    plot_width = ORBIT_WIDTH - ORBIT_LEFT - ORBIT_RIGHT
    plot_height = ORBIT_HEIGHT - ORBIT_TOP - ORBIT_BOTTOM
    body = [
        _element(
            "rect",
            x=_number(ORBIT_LEFT),
            y=_number(ORBIT_TOP),
            width=_number(plot_width),
            height=_number(plot_height),
            fill="none",
            stroke="#999999",
            stroke_width="1",
        )
    ]
    for inclination in (0.0, 30.0, 60.0, 90.0):
        x = ORBIT_LEFT + plot_width * inclination / ORBIT_MAX_INCLINATION
        body.append(
            _element(
                "line",
                x1=_number(x),
                y1=_number(ORBIT_TOP),
                x2=_number(x),
                y2=_number(ORBIT_TOP + plot_height),
                stroke="#eeeeee",
                stroke_width="1",
            )
        )
        body.append(
            _element(
                "text",
                f"{inclination:.0f}",
                x=_number(x),
                y=_number(ORBIT_TOP + plot_height + 20.0),
                fill="#333333",
                font_size="13",
                text_anchor="middle",
            )
        )
    for step in range(5):
        radius = ORBIT_MIN_RADIUS + step * 5.0e6
        y = _radius_axis(radius)
        body.append(
            _element(
                "line",
                x1=_number(ORBIT_LEFT),
                y1=_number(y),
                x2=_number(ORBIT_LEFT + plot_width),
                y2=_number(y),
                stroke="#eeeeee",
                stroke_width="1",
            )
        )
        body.append(
            _element(
                "text",
                f"{radius / 1e6:.0f}",
                x=_number(ORBIT_LEFT - 12.0),
                y=_number(y + 4.0),
                fill="#333333",
                font_size="13",
                text_anchor="end",
            )
        )
    body.append(
        _element(
            "text",
            "inclination / deg",
            x=_number(ORBIT_LEFT + plot_width / 2),
            y=_number(ORBIT_HEIGHT - 18.0),
            fill="#333333",
            font_size="14",
            text_anchor="middle",
        )
    )
    body.append(
        _element(
            "text",
            "orbital radius / Mm",
            x=_number(20.0),
            y=_number(ORBIT_TOP - 24.0),
            fill="#333333",
            font_size="14",
            text_anchor="start",
        )
    )
    for satellite in satellites:
        x = ORBIT_LEFT + plot_width * satellite.inclination / ORBIT_MAX_INCLINATION
        y = _radius_axis(satellite.radius)
        body.append(
            _element(
                "g",
                _element(
                    "circle",
                    cx=_number(x),
                    cy=_number(y),
                    r="5",
                    fill=COLOURS[satellite.system],
                    fill_opacity="0.75",
                    stroke="#ffffff",
                    stroke_width="0.5",
                    class_="marker",
                ),
                class_="satellite",
                data_prn=str(satellite.prn),
                data_constellation=satellite.system.value,
            )
        )
    return _document(ORBIT_WIDTH, ORBIT_HEIGHT, [_title("orbit plot"), *body])


def _radius_axis(radius: float) -> float:
    plot_height = ORBIT_HEIGHT - ORBIT_TOP - ORBIT_BOTTOM
    fraction = (radius - ORBIT_MIN_RADIUS) / (ORBIT_MAX_RADIUS - ORBIT_MIN_RADIUS)
    return ORBIT_TOP + plot_height * (1.0 - fraction)


def table_plot(satellites: Sequence[NavigationSatellite]) -> str:
    """Per-satellite table figure of the decoded orbital elements."""
    body = [_title("navigation messages")]
    for column, heading in zip(TABLE_COLUMNS, TABLE_HEADINGS, strict=True):
        body.append(
            _element(
                "text",
                heading,
                x=_number(column),
                y=_number(TABLE_TOP - 24.0),
                fill="#333333",
                font_size="15",
                text_anchor="start",
                class_="heading",
            )
        )
    for index, satellite in enumerate(satellites):
        y = TABLE_TOP + index * TABLE_ROW_HEIGHT
        cells = (
            str(satellite.prn),
            satellite.system.value,
            f"{satellite.semi_major_axis / 1000.0:.3f}",
            f"{satellite.eccentricity:.7f}",
            f"{satellite.inclination:.3f}",
            f"{satellite.radius / 1000.0:.3f}",
            f"{satellite.clock_bias * 1e9:.3f}",
        )
        rows = []
        for column, cell in zip(TABLE_COLUMNS, cells, strict=True):
            rows.append(
                _element(
                    "text",
                    cell,
                    x=_number(column),
                    y=_number(y),
                    fill="#333333",
                    font_size="13",
                    text_anchor="start",
                    class_="cell",
                )
            )
        body.append(
            _element(
                "g",
                "".join(rows),
                class_="row",
                data_prn=str(satellite.prn),
                data_constellation=satellite.system.value,
            )
        )
    height = TABLE_TOP + len(satellites) * TABLE_ROW_HEIGHT + 40.0
    return _document(TABLE_WIDTH, height, body)


def _title(caption: str) -> str:
    return _element(
        "text",
        caption,
        x="20",
        y="34",
        fill="#111111",
        font_size="20",
        text_anchor="start",
        class_="title",
    )


def _document(width: float, height: float, body: Sequence[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}"'
        f' height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">\n'
        + "".join(body)
        + "\n</svg>\n"
    )


def _element(name: str, content: str = "", **attributes: str) -> str:
    rendered = " ".join(
        f'{key.rstrip("_").replace("_", "-")}="{value}"'
        for key, value in attributes.items()
    )
    if not content:
        return f"<{name} {rendered}/>"
    return f"<{name} {rendered}>{content}</{name}>"


def _number(value: float) -> str:
    return f"{value:.3f}"


def satellite_csv(satellites: Sequence[NavigationSatellite]) -> str:
    """Per-satellite rows of the decoded orbital elements as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        (
            "prn",
            "constellation",
            "orbit_regime",
            "semi_major_axis_m",
            "eccentricity",
            "inclination_deg",
            "radius_m",
            "clock_bias_s",
            "azimuth_deg",
            "elevation_deg",
        )
    )
    for satellite in satellites:
        writer.writerow(
            (
                satellite.prn,
                satellite.system.value,
                satellite.orbit_regime.value,
                f"{satellite.semi_major_axis:.3f}",
                f"{satellite.eccentricity:.9f}",
                f"{satellite.inclination:.6f}",
                f"{satellite.radius:.3f}",
                f"{satellite.clock_bias:.12e}",
                f"{satellite.azimuth:.6f}",
                f"{satellite.elevation:.6f}",
            )
        )
    return buffer.getvalue()


def satellite_payload(
    satellites: Sequence[NavigationSatellite],
) -> dict[str, object]:
    """JSON-ready report of every decoded satellite."""
    return {
        "count": len(satellites),
        "satellites": [
            {
                "prn": satellite.prn,
                "constellation": satellite.system.value,
                "orbit_class": satellite.orbit_regime.value,
                "semi_major_axis": satellite.semi_major_axis,
                "eccentricity": satellite.eccentricity,
                "inclination": satellite.inclination,
                "radius": satellite.radius,
                "clock_bias": satellite.clock_bias,
                "azimuth": satellite.azimuth,
                "elevation": satellite.elevation,
            }
            for satellite in satellites
        ],
    }


def figures(satellites: Sequence[NavigationSatellite]) -> dict[str, str]:
    """The three SVG documents keyed by their file name."""
    return {
        "sky_plot.svg": sky_plot(satellites),
        "orbit_plot.svg": orbit_plot(satellites),
        "table.svg": table_plot(satellites),
    }
