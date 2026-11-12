"""RINEX 3.05 broadcast navigation export from receiver ephemerides."""
# RINEX L2 code, L2 P-data and fit interval fields remain blank because the
# receiver leaves them unspecified. Transmission time uses the RINEX sentinel
# until the receiver's `tow` is verified as the transmission time.

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from os import PathLike
from pathlib import Path
from typing import Literal

from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.rinex import _header

_WEEK = 604800
_GPS_EPOCH = datetime(1980, 1, 6)
_BDT_EPOCH = datetime(2006, 1, 1)
_BDT_GPS_WEEKS = 1356


@dataclass(frozen=True, slots=True)
class RinexNavigationExport:
    text: str
    messages: int
    unknown_fields: tuple[str, ...]

    def write(self, path: str | PathLike[str]) -> Path:
        """Write the RINEX navigation file, replacing an existing file."""
        destination = Path(path)
        destination.write_text(self.text, encoding="ascii", newline="\n")
        return destination


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


def _receiver_epoch(record: Record) -> tuple[int, float]:
    if record.message is None:
        raise ValueError(f"{record.name} requires a receiver timestamp")
    epoch = gps_epoch(record.message)
    week, seconds = divmod(epoch, _WEEK)
    return int(week), seconds


def _galileo_sisa(index: int) -> float:
    if index < 0:
        raise ValueError("Galileo SISA index is unavailable or reserved")
    if 0 <= index <= 49:
        return index * 0.01
    if index <= 74:
        return 0.5 + (index - 50) * 0.02
    if index <= 99:
        return 1 + (index - 75) * 0.04
    if index <= 125:
        return 2 + (index - 100) * 0.16
    raise ValueError("Galileo SISA index is unavailable or reserved")


def _galileo(record: Record, inav_sources: frozenset[str]) -> list[list[str]]:
    prn, iod = record.integer("satid"), record.integer("iodnav")
    if not 1 <= prn <= 36 or not 0 <= iod <= 1023:
        raise ValueError("invalid Galileo satellite or IODnav")
    flags = (record["fnavreceived"], record["inavreceived"])
    if any(flag not in (True, 1, "TRUE") for flag in flags):
        raise ValueError("Galileo export requires both F/NAV and I/NAV health fields")
    health = 0
    for index, name in enumerate(("e1b", "e5a", "e5b")):
        hs, dvs = record.integer(name + "health"), record.integer(name + "dvs")
        if not 0 <= hs <= 3 or dvs not in (0, 1):
            raise ValueError("invalid Galileo signal health or validity")
        health |= (dvs | (hs << 1)) << (index * 3)
    gps_week, gps_sow = _receiver_epoch(record)
    toe = record.integer("toe")
    if not 0 <= toe < _WEEK:
        raise ValueError("invalid Galileo ephemeris time")
    week = _week_of(gps_week, gps_sow, toe)
    root_a = record.real("roota")
    if not math.isfinite(root_a) or root_a <= 0:
        raise ValueError("invalid Galileo semi-major axis")
    result = []
    inav_code = (
        512 | (1 if "E1B" in inav_sources else 0) | (4 if "E5B" in inav_sources else 0)
    )
    for kind, code in (("inav", inav_code), ("fnav", 258)):
        toc = record.integer(kind + "t0c")
        if not 0 <= toc < _WEEK:
            raise ValueError("invalid Galileo clock time")
        clock_week = _week_of(week, toe, toc)
        stamp = _GPS_EPOCH + timedelta(weeks=clock_week, seconds=toc)
        line = f"E{prn:02d} {stamp:%Y %m %d %H %M %S}" + "".join(
            _number(record.real(kind + field)) for field in ("af0", "af1", "af2")
        )
        rows: tuple[tuple[float | int | None, ...], ...] = (
            (iod, record.real("crs"), record.real("deltan"), record.real("m0")),
            (record.real("cuc"), record.real("ecc"), record.real("cus"), root_a),
            (toe, record.real("cic"), record.real("omega0"), record.real("cis")),
            (
                record.real("i0"),
                record.real("crc"),
                record.real("omega"),
                record.real("omegadot"),
            ),
            (record.real("idot"), code, week, None),
            (
                _galileo_sisa(record.integer("sisa")),
                health & (0b111000111 if kind == "inav" else 0b111000),
                record.real("e1e5abgd"),
                record.real("e1e5bbgd") if kind == "inav" else 0,
            ),
            (999999999.999, None, None, None),
        )
        result.append([line, *("    " + "".join(map(_number, row)) for row in rows)])
    return result


def _beidou(record: Record, time_scale: Literal["BDT", "GPST"]) -> list[str]:
    prn = record.integer("prn")
    if not 1 <= prn <= 63 or record.integer("aode") != record.integer("aode_2"):
        raise ValueError("invalid BeiDou PRN or inconsistent AODE")
    if record.integer("health") not in (0, 1):
        raise ValueError("invalid BeiDou health")
    axis, ura = record.real("a"), record.real("ura")
    if not math.isfinite(axis) or axis <= 0 or not math.isfinite(ura) or ura < 0:
        raise ValueError("invalid BeiDou semi-major axis or URA variance")
    gps_week, gps_sow = _receiver_epoch(record)
    bdt_reference = gps_week * _WEEK + gps_sow - 14 - _BDT_GPS_WEEKS * _WEEK
    bdt_week, bdt_sow = divmod(bdt_reference, _WEEK)

    def bdt_time(seconds: float) -> tuple[int, float]:
        if not math.isfinite(seconds) or not 0 <= seconds < _WEEK:
            raise ValueError("invalid BeiDou ephemeris time")
        if time_scale == "BDT":
            return _week_of(int(bdt_week), bdt_sow, seconds), seconds
        week = _week_of(gps_week, gps_sow, seconds)
        result_week, result_sow = divmod(
            (week - _BDT_GPS_WEEKS) * _WEEK + seconds - 14, _WEEK
        )
        return int(result_week), result_sow

    toe_week, toe = bdt_time(record.real("toe"))
    toc_week, toc = bdt_time(record.real("toc"))
    if toe_week < 0 or toc_week < 0 or toc != int(toc):
        raise ValueError("invalid BeiDou clock epoch")
    if abs(record.integer("week") - (toe_week + _BDT_GPS_WEEKS)) > 1:
        raise ValueError("BeiDou ephemeris week disagrees with receiver timestamp")
    stamp = _BDT_EPOCH + timedelta(weeks=toc_week, seconds=toc)
    line = f"C{prn:02d} {stamp:%Y %m %d %H %M %S}" + "".join(
        _number(record.real(field)) for field in ("af0", "af1", "af2")
    )
    rows: tuple[tuple[float | int | None, ...], ...] = (
        (
            record.integer("aode"),
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
            record.real("tgd1"),
            record.real("tgd2"),
        ),
        (999999999.999, record.integer("aodc"), None, None),
    )
    return [line, *("    " + "".join(map(_number, row)) for row in rows)]


def _glonass(record: Record, leap_seconds: int, version: str) -> list[str]:
    slot = record.integer("sloto") - 37
    frequency = record.integer("freqo") - 7
    week, milliseconds = record.integer("e_week"), record.integer("e_time")
    health, age, frame_time = (
        record.integer("health"),
        record.integer("age"),
        record.integer("tk"),
    )
    if not 1 <= slot <= 24 or not -7 <= frequency <= 13:
        raise ValueError("invalid GLONASS slot or frequency channel")
    if not 0 <= week <= 65535 or not 0 <= milliseconds < _WEEK * 1000:
        raise ValueError("invalid GLONASS reference epoch")
    if milliseconds % 1000 or health not in (0, 1) or not 0 <= age <= 31:
        raise ValueError("invalid GLONASS epoch, health or age")
    if not 0 <= frame_time < 86400:
        raise ValueError("invalid GLONASS frame time")
    stamp = _GPS_EPOCH + timedelta(
        weeks=week, milliseconds=milliseconds, seconds=-leap_seconds
    )
    midnight = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = midnight + timedelta(seconds=frame_time - 10800)
    candidates = (
        candidate - timedelta(days=1),
        candidate,
        candidate + timedelta(days=1),
    )
    frame = min(candidates, key=lambda value: abs((value - stamp).total_seconds()))
    frame_sow = (frame - _GPS_EPOCH).total_seconds() % _WEEK
    line = f"R{slot:02d} {stamp:%Y %m %d %H %M %S}" + "".join(
        map(_number, (-record.real("tau_n"), record.real("gamma"), frame_sow))
    )
    rows: list[tuple[float | int | None, ...]] = [
        (
            record.real("pos_x") / 1000,
            record.real("vel_x") / 1000,
            record.real("ls_acc_x") / 1000,
            health,
        ),
        (
            record.real("pos_y") / 1000,
            record.real("vel_y") / 1000,
            record.real("ls_acc_y") / 1000,
            frequency,
        ),
        (
            record.real("pos_z") / 1000,
            record.real("vel_z") / 1000,
            record.real("ls_acc_z") / 1000,
            age,
        ),
    ]
    if version == "3.05":
        rows.append((None, 999999999.999, 15, None))
    return [line, *("    " + "".join(map(_number, row)) for row in rows)]


def export_rinex_navigation(
    records: Sequence[Record],
    *,
    bdseph_time_scale: Literal["BDT", "GPST"] | None = None,
    galileo_inav_sources: frozenset[str] | None = None,
    glonass_leap_seconds: int | None = None,
    version: Literal["3.04", "3.05"] = "3.05",
) -> RinexNavigationExport:
    """Export broadcast ephemerides with explicit time and signal conventions."""
    if not records:
        raise ValueError("at least one ephemeris record is required")
    if bdseph_time_scale not in (None, "BDT", "GPST"):
        raise ValueError("bdseph_time_scale must be BDT or GPST")
    if version not in ("3.04", "3.05"):
        raise ValueError("version must be 3.04 or 3.05")
    systems = {record.name for record in records}
    unsupported = systems - {"GPSEPH", "GALEPH", "BDSEPH", "GLOEPH"}
    if unsupported:
        raise ValueError(f"unsupported ephemeris records: {sorted(unsupported)}")
    if "BDSEPH" in systems and bdseph_time_scale is None:
        raise ValueError("BDSEPH time scale must be supplied after verification")
    if "GALEPH" in systems and (
        not galileo_inav_sources or not galileo_inav_sources <= {"E1B", "E5B"}
    ):
        raise ValueError(
            "Galileo I/NAV source signals must be supplied after verification"
        )
    if "GLOEPH" in systems and (
        not isinstance(glonass_leap_seconds, int)
        or isinstance(glonass_leap_seconds, bool)
        or not 0 <= glonass_leap_seconds <= 99
    ):
        raise ValueError(
            "GLONASS GPS-UTC leap seconds must be supplied after verification"
        )
    labels = {
        "GPSEPH": "G: GPS",
        "GALEPH": "E: Galileo",
        "BDSEPH": "C: BDS",
        "GLOEPH": "R: GLONASS",
    }
    system_label = labels[next(iter(systems))] if len(systems) == 1 else "M: Mixed"
    lines = [
        _header(
            f"{version:>9}{'':11}{'N: GNSS NAV DATA':<20}{system_label}",
            "RINEX VERSION / TYPE",
        ),
        _header(
            f"{'um982py':<20}{'':20}{datetime.now(UTC):%Y%m%d %H%M%S UTC}",
            "PGM / RUN BY / DATE",
        ),
    ]
    if systems - {"GLOEPH"}:
        lines.append(
            _header("Transmission time unknown; RINEX sentinel used", "COMMENT")
        )
    unknown: list[str] = []
    if "GPSEPH" in systems:
        lines.append(_header("L2 codes, L2 P flag and fit interval unknown", "COMMENT"))
        unknown.extend(("l2_codes", "l2_p_data_flag", "fit_interval"))
    if "GALEPH" in systems:
        signals = ",".join(sorted(galileo_inav_sources or ()))
        lines.append(_header(f"I/NAV source signals supplied: {signals}", "COMMENT"))
    if "BDSEPH" in systems:
        lines.append(
            _header(f"BDSEPH source time scale: {bdseph_time_scale}", "COMMENT")
        )
    if "GLOEPH" in systems:
        lines.append(
            _header(f"GPS-UTC leap seconds supplied: {glonass_leap_seconds}", "COMMENT")
        )
        if version == "3.05":
            unknown.extend(
                (
                    "glonass_status_flags",
                    "glonass_l1_l2_delay",
                    "glonass_accuracy_index",
                    "glonass_health_flags",
                )
            )
    lines.append(_header("", "END OF HEADER"))
    messages = 0
    for record in records:
        if record.name == "GPSEPH":
            lines.extend(_gps(record))
            messages += 1
        elif record.name == "GALEPH":
            if not galileo_inav_sources:
                raise ValueError("Galileo I/NAV source signals must be supplied")
            for navigation in _galileo(record, galileo_inav_sources):
                lines.extend(navigation)
                messages += 1
        elif record.name == "BDSEPH":
            if bdseph_time_scale is None:
                raise ValueError(
                    "BDSEPH time scale must be supplied after verification"
                )
            lines.extend(_beidou(record, bdseph_time_scale))
            messages += 1
        else:
            if glonass_leap_seconds is None:
                raise ValueError("GLONASS GPS-UTC leap seconds must be supplied")
            lines.extend(_glonass(record, glonass_leap_seconds, version))
            messages += 1
    if systems - {"GLOEPH"}:
        unknown.append("transmission_time")
    return RinexNavigationExport(
        "\n".join(lines) + "\n",
        messages,
        tuple(unknown),
    )
