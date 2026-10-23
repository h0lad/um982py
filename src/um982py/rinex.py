"""Uncompressed receiver observations exported to RINEX 3.05."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.signals import tracking_signal

_LETTERS = "GRSECJI"
_GLONASS_CHANNEL_OFFSET = 7
_GPS_EPOCH = datetime(1980, 1, 6)


@dataclass(frozen=True, slots=True)
class RinexExport:
    text: str
    epochs: int
    satellite_records: int
    signal_observations: int
    omitted: dict[str, int]


@dataclass(frozen=True, slots=True)
class RinexMetadata:
    """User-supplied station metadata with coordinates and ARP offsets in metres.

    XYZ is the geocentric marker position, while H/E/N is the antenna reference point
    relative to the marker, not an antenna phase-centre correction.
    """

    observer: str = ""
    agency: str = ""
    receiver_number: str = ""
    receiver_type: str = ""
    receiver_version: str = ""
    antenna_number: str = ""
    antenna_type: str = ""
    position_xyz: tuple[float, float, float] | None = None
    antenna_delta_hen: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        for value, width, name in (
            (self.observer, 20, "observer"),
            (self.agency, 40, "agency"),
            (self.receiver_number, 20, "receiver number"),
            (self.receiver_type, 20, "receiver type"),
            (self.receiver_version, 20, "receiver version"),
            (self.antenna_number, 20, "antenna number"),
            (self.antenna_type, 20, "antenna type"),
        ):
            _text_field(value, width, name)
        _vector_field(self.position_xyz, "position XYZ")
        _vector_field(self.antenna_delta_hen, "antenna delta H/E/N")


def _text_field(value: str, width: int, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or len(value) > width
    ):
        raise ValueError(f"invalid RINEX {name}")
    return f"{value:<{width}}"


def _vector_field(value: tuple[float, float, float] | None, name: str) -> str:
    if value is None:
        return "".join(f"{0.0:14.4f}" for _ in range(3))
    if len(value) != 3 or any(not math.isfinite(v) for v in value):
        raise ValueError(f"invalid RINEX {name}")
    fields = [f"{v:14.4f}" for v in value]
    if any(len(field) != 14 for field in fields):
        raise ValueError(f"RINEX {name} exceeds field width")
    return "".join(fields)


def satellite_id(system: int, wire_prn: int) -> str | None:
    """Translate Unicore RANGE PRNs to RINEX satellite identifiers."""
    if system == 1:
        prn, low, high = wire_prn - 37, 1, 24
    elif system == 2:
        prn, low, high = wire_prn - 100, 20, 58
    elif system == 5:
        prn, low, high = wire_prn - 192, 1, 10
    else:
        prn, low, high = wire_prn, 1, {0: 32, 3: 36, 4: 63, 6: 15}.get(system, 0)
    return f"{_LETTERS[system]}{prn:02d}" if low <= prn <= high else None


def _header(content: str, label: str) -> str:
    if not content.isascii() or len(content) > 60 or any(c in content for c in "\r\n"):
        raise ValueError(f"invalid {label} header content")
    return f"{content:<60}{label}"


type Epoch = tuple[float, dict[str, dict[str, Record]]]


def _observation(row: Record, name: str) -> Record:
    if name not in ("OBSVM", "OBSVH", "OBSVBASE"):
        return row
    return Record(
        "observation",
        (
            ("prn", row.integer("prn_slot")),
            ("frequency_channel", row.integer("system_freq")),
            ("pseudorange", row.real("psr")),
            ("carrier_phase", row.real("adr")),
            ("doppler", row.real("dopp")),
            ("cn0", row.real("c_n0") / 100),
            ("lock_time", row.real("locktime")),
            ("tracking_status", row.integer("ch_tr_status")),
        ),
    )


def _collect_epochs(
    records: Sequence[Record],
    l2c_code: str | None,
    omitted: Counter[str],
    week_scale: Literal["GPST", "BDT"] | None,
) -> tuple[list[Epoch], dict[str, set[str]], dict[str, int]]:
    types: dict[str, set[str]] = {}
    channels: dict[str, int] = {}
    epochs: list[Epoch] = []
    for record in records:
        if record.message is None:
            raise ValueError("RANGE needs a receiver timestamp")
        epoch = gps_epoch(record.message, week_scale=week_scale)
        if epochs and epoch <= epochs[-1][0]:
            raise ValueError("RANGE epochs must be strictly increasing")
        satellites: dict[str, dict[str, Record]] = {}
        for native in record.records("observations"):
            observation = _observation(native, record.name)
            status = observation.integer("tracking_status")
            signal = tracking_signal(status, l2c_code=l2c_code)
            if signal is not None and not signal.rinex_code and signal.signal == 9:
                omitted["unverified_l2c_component"] += 1
                continue
            if signal is not None and signal.system == 5 and signal.signal == 0:
                omitted["ambiguous_qzss_l1"] += 1
                continue
            if signal is None or not signal.rinex_code:
                omitted["unknown_signal"] += 1
                continue
            satellite = satellite_id(signal.system, observation.integer("prn"))
            if satellite is None:
                omitted["unknown_satellite"] += 1
                continue
            if status & 0x1400 != 0x1400:
                omitted["invalid_code_or_phase"] += 1
            if not status & 0x1400:
                continue
            values = tuple(
                observation.real(field)
                for field in (
                    "pseudorange",
                    "carrier_phase",
                    "doppler",
                    "cn0",
                    "lock_time",
                )
            )
            if not all(math.isfinite(value) for value in values):
                omitted["invalid_numeric_value"] += 1
                continue
            if status & 0x1000 and values[0] <= 0:
                omitted["invalid_numeric_value"] += 1
                if not status & 0x0400:
                    continue
            if signal.system == 1 and signal.signal in (0, 5):
                channel = (
                    observation.integer("frequency_channel") - _GLONASS_CHANNEL_OFFSET
                )
                if not -7 <= channel <= 6:
                    omitted["invalid_glonass_channel"] += 1
                    continue
                if satellite in channels and channels[satellite] != channel:
                    raise ValueError(f"GLONASS channel changed for {satellite}")
                channels[satellite] = channel
            group = satellites.setdefault(satellite, {})
            previous = group.get(signal.rinex_code)
            if previous is not None:
                omitted["duplicate_signal"] += 1
            if previous is None or (
                ((status & 0x1400).bit_count(), observation.real("cn0"))
                > (
                    (previous.integer("tracking_status") & 0x1400).bit_count(),
                    previous.real("cn0"),
                )
            ):
                group[signal.rinex_code] = observation
                types.setdefault(satellite[0], set()).add(signal.rinex_code)
        epochs.append((epoch, satellites))
    return epochs, types, channels


def _observable_codes(types: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    return {
        system: tuple(
            f"{kind}{signal}" for signal in sorted(signals) for kind in "CLDS"
        )
        for system, signals in types.items()
    }


def _header_lines(
    records: Sequence[Record],
    marker_name: str,
    l2c_code: str | None,
    omitted: Counter[str],
    codes: dict[str, tuple[str, ...]],
    channels: dict[str, int],
    first_epoch: float,
    week_scale: Literal["GPST", "BDT"] | None,
    metadata: RinexMetadata,
) -> list[str]:
    stamp = _GPS_EPOCH + timedelta(seconds=first_epoch)
    created = datetime.now(UTC).strftime("%Y%m%d %H%M%S UTC")
    lines = [
        _header(f"{'3.05':>9}{'':11}{'OBSERVATION DATA':<20}M", "RINEX VERSION / TYPE"),
        _header(f"{'um982py':<20}{'':20}{created:<20}", "PGM / RUN BY / DATE"),
        _header(marker_name, "MARKER NAME"),
        _header("GEODETIC", "MARKER TYPE"),
        _header(
            _text_field(metadata.observer, 20, "observer")
            + _text_field(metadata.agency, 40, "agency"),
            "OBSERVER / AGENCY",
        ),
        _header(
            _text_field(metadata.receiver_number, 20, "receiver number")
            + _text_field(metadata.receiver_type, 20, "receiver type")
            + _text_field(metadata.receiver_version, 20, "receiver version"),
            "REC # / TYPE / VERS",
        ),
        _header(
            _text_field(metadata.antenna_number, 20, "antenna number")
            + _text_field(metadata.antenna_type, 20, "antenna type"),
            "ANT # / TYPE",
        ),
        _header(
            _vector_field(metadata.position_xyz, "position XYZ"), "APPROX POSITION XYZ"
        ),
        _header(
            _vector_field(metadata.antenna_delta_hen, "antenna delta H/E/N"),
            "ANTENNA: DELTA H/E/N",
        ),
        _header(f"Native {records[0].name} input; GPST epochs", "COMMENT"),
    ]
    if metadata.position_xyz is None:
        lines.append(
            _header("Approximate position unknown; zeros are placeholders", "COMMENT")
        )
    if metadata.antenna_delta_hen is None:
        lines.append(
            _header("Antenna delta unknown; zeros are placeholders", "COMMENT")
        )
    lines.append(_header("Antenna phase-centre corrections not applied", "COMMENT"))
    if week_scale is not None:
        lines.append(
            _header(f"Input week scale supplied by caller: {week_scale}", "COMMENT")
        )
    if l2c_code is not None:
        lines.append(
            _header(f"Type-9 L2C attribute supplied by caller: {l2c_code}", "COMMENT")
        )
    if omitted.get("unverified_l2c_component"):
        lines.append(
            _header("Type-9 L2C omitted: component attribute unverified", "COMMENT")
        )
    for system, observables in sorted(codes.items()):
        for start in range(0, len(observables), 13):
            prefix = f"{system}  {len(observables):3d}" if start == 0 else "      "
            lines.append(
                _header(
                    prefix
                    + "".join(f" {code}" for code in observables[start : start + 13]),
                    "SYS / # / OBS TYPES",
                )
            )
    # RINEX 3.05 requires one record per system when phase alignment is
    # unknown. Do not claim zero corrections without receiver evidence.
    lines.extend(_header(system, "SYS / PHASE SHIFT") for system in sorted(codes))
    if channels:
        slots = sorted(channels)
        for start in range(0, len(slots), 8):
            prefix = f"{len(slots):3d}" if start == 0 else "   "
            lines.append(
                _header(
                    prefix
                    + "".join(
                        f" {satellite} {channels[satellite]:2d}"
                        for satellite in slots[start : start + 8]
                    ),
                    "GLONASS SLOT / FRQ #",
                )
            )
        lines.append(_header("", "GLONASS COD/PHS/BIS"))
    lines.extend(
        (
            _header(
                f"{stamp.year:6d}{stamp.month:6d}{stamp.day:6d}{stamp.hour:6d}"
                f"{stamp.minute:6d}{stamp.second + stamp.microsecond / 1e6:13.7f}"
                "     GPS",
                "TIME OF FIRST OBS",
            ),
            _header("DBHZ", "SIGNAL STRENGTH UNIT"),
            _header("", "END OF HEADER"),
        )
    )
    return lines


def _epoch_lines(
    epochs: Sequence[Epoch],
    codes: dict[str, tuple[str, ...]],
) -> tuple[list[str], int, int]:
    previous_lock: dict[tuple[str, str], float] = {}
    lines: list[str] = []
    satellite_count = observation_count = 0
    for epoch, satellites in epochs:
        stamp = _GPS_EPOCH + timedelta(seconds=epoch)
        lines.append(
            f"> {stamp:%Y %m %d %H %M} "
            f"{stamp.second + stamp.microsecond / 1e6:10.7f}  0{len(satellites):3d}"
        )
        satellite_count += len(satellites)
        for satellite, group in sorted(satellites.items()):
            fields = []
            observation_count += len(group)
            for code in codes[satellite[0]]:
                row = group.get(code[1:])
                if row is None:
                    fields.append(" " * 16)
                    continue
                status = row.integer("tracking_status")
                if (
                    code[0] == "C"
                    and (not status & 0x1000 or row.real("pseudorange") <= 0)
                ) or (code[0] in ("L", "D") and not status & 0x0400):
                    fields.append(" " * 16)
                    continue
                value = {
                    "C": row.real("pseudorange"),
                    "L": -row.real("carrier_phase"),
                    "D": row.real("doppler"),
                    "S": row.real("cn0"),
                }[code[0]]
                flag = " "
                if code[0] == "L":
                    key = satellite, code[1:]
                    lock = row.real("lock_time")
                    if key in previous_lock and lock < previous_lock[key]:
                        flag = "1"
                    previous_lock[key] = lock
                field = f"{value:14.3f}{flag} "
                if len(field) != 16:
                    raise ValueError("observation exceeds RINEX field width")
                fields.append(field)
            lines.append(satellite + "".join(fields))
    return lines, satellite_count, observation_count


def export_rinex(
    records: Sequence[Record],
    *,
    marker_name: str = "UM982",
    l2c_code: str | None = None,
    week_scale: Literal["GPST", "BDT"] | None = None,
    metadata: RinexMetadata | None = None,
) -> RinexExport:
    """Export valid observables and report omitted or partially invalid signals.

    ``invalid_code_or_phase`` counts signal records missing either validity
    flag, although a valid code or phase can still be exported.
    """
    if not records or any(
        record.name not in ("RANGE", "RANGEH", "OBSVM", "OBSVH", "OBSVBASE")
        for record in records
    ):
        raise ValueError(
            "uncompressed RANGE, RANGEH, OBSVM, OBSVH or OBSVBASE records are required"
        )
    if len({record.name for record in records}) != 1:
        raise ValueError("export one antenna per RINEX file")
    omitted: Counter[str] = Counter()
    epochs, types, channels = _collect_epochs(records, l2c_code, omitted, week_scale)
    if not types:
        raise ValueError("no exportable valid RANGE observations")
    codes = _observable_codes(types)
    lines = _header_lines(
        records,
        marker_name,
        l2c_code,
        omitted,
        codes,
        channels,
        epochs[0][0],
        week_scale,
        metadata if metadata is not None else RinexMetadata(),
    )
    epoch_lines, satellite_count, observation_count = _epoch_lines(epochs, codes)
    lines.extend(epoch_lines)
    return RinexExport(
        "\n".join(lines) + "\n",
        len(epochs),
        satellite_count,
        observation_count,
        dict(omitted),
    )
