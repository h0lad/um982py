"""RINEX 3.05 GPS LNAV export from documented UM982 GPSEPH records."""
#  The receiver does not expose every LNAV field required by RINEX: L2 code,
# L2 P-data and fit interval are left blank. Transmission time is marked
# unknown using the RINEX-defined sentinel, since the receiver's `tow` is not
# independently established as the transmitted message time.

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from um982py.messages import Record
from um982py.rinex import _header

_WEEK = 604800
_GPS_EPOCH = datetime(1980, 1, 6)


@dataclass(frozen=True, slots=True)
class RinexNavigationExport:
    text: str
    messages: int
    unknown_fields: tuple[str, ...]


def _number(value: float | int | None) -> str:
    if value is None:
        return " " * 19
    if not math.isfinite(value):
        raise ValueError("navigation field must be finite")
    result = f"{value:19.12E}".replace("E", "D")
    if len(result) != 19:
        raise ValueError("navigation field exceeds RINEX width")
    return result


def _week_of(reference_week: int, reference_sow: float, target_sow: float) -> int:
    difference = target_sow - reference_sow
    if difference > _WEEK / 2:
        return reference_week - 1
    if difference < -_WEEK / 2:
        return reference_week + 1
    return reference_week


def _gps(record: Record) -> list[str]:
    if record.name != "GPSEPH":
        raise ValueError("RINEX navigation export currently supports GPSEPH only")
    prn, week = record.integer("prn"), record.integer("week")
    tow, toe, toc = record.real("tow"), record.real("toe"), record.real("toc")
    if not 1 <= prn <= 32 or not 0 <= week <= 65535:
        raise ValueError("invalid GPS PRN or week")
    if any(not math.isfinite(x) or not 0 <= x < _WEEK for x in (tow, toe, toc)):
        raise ValueError("GPS ephemeris times must be finite seconds of week")
    if toc != int(toc):
        raise ValueError("RINEX navigation clock epoch requires whole seconds")
    if record.integer("iode1") != record.integer("iode2"):
        raise ValueError("GPS ephemeris issue numbers do not match")
    if not 0 <= record.integer("health") <= 63:
        raise ValueError("GPS health is not a six-bit value")
    axis, ura = record.real("a"), record.real("ura")
    if not math.isfinite(axis) or axis <= 0 or not math.isfinite(ura) or ura < 0:
        raise ValueError("invalid GPS semi-major axis or URA variance")
    toe_week = _week_of(week, tow, toe)
    toc_week = _week_of(toe_week, toe, toc)
    stamp = _GPS_EPOCH + timedelta(weeks=toc_week, seconds=toc)
    line = f"G{prn:02d} {stamp:%Y %m %d %H %M %S}" + "".join(
        _number(record.real(field)) for field in ("af0", "af1", "af2")
    )
    rows: tuple[tuple[float | int | None, ...], ...] = (
        (
            record.integer("iode1"),
            record.real("crs"),
            record.real("delta_n"),
            record.real("m0"),
        ),
        (record.real("cuc"), record.real("ecc"), record.real("cus"), math.sqrt(axis)),
        (toe, record.real("cic"), record.real("omega_0"), record.real("cis")),
        (
            record.real("i0"),
            record.real("crc"),
            record.real("omega"),
            record.real("omega_dot"),
        ),
        (record.real("idot"), None, toe_week, None),
        (
            math.sqrt(ura),
            record.integer("health"),
            record.real("tgd"),
            record.integer("iodc"),
        ),
        (999999999.999, None, None, None),
    )
    return [line, *("    " + "".join(map(_number, row)) for row in rows)]


def export_rinex_navigation(records: Sequence[Record]) -> RinexNavigationExport:
    """Export GPS ephemerides without inferring unavailable navigation fields."""
    if not records:
        raise ValueError("at least one GPSEPH record is required")
    lines = [
        _header(
            f"{'3.05':>9}{'':11}{'N: GNSS NAV DATA':<20}G: GPS", "RINEX VERSION / TYPE"
        ),
        _header(
            f"{'um982py':<20}{'':20}{datetime.now(UTC):%Y%m%d %H%M%S UTC}",
            "PGM / RUN BY / DATE",
        ),
        _header("L2 codes, L2 P flag and fit interval unknown", "COMMENT"),
        _header("Transmission time unknown; RINEX sentinel used", "COMMENT"),
        _header("", "END OF HEADER"),
    ]
    for record in records:
        lines.extend(_gps(record))
    return RinexNavigationExport(
        "\n".join(lines) + "\n",
        len(records),
        ("l2_codes", "l2_p_data_flag", "fit_interval", "transmission_time"),
    )
