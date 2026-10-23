"""Merge GPS observations from bounded um982py RINEX recording segments."""

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

_IDENTITY = (
    "MARKER NAME",
    "MARKER TYPE",
    "OBSERVER / AGENCY",
    "REC # / TYPE / VERS",
    "ANT # / TYPE",
    "APPROX POSITION XYZ",
    "ANTENNA: DELTA H/E/N",
)


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Counts of merged epochs and conservative carrier-arc resets."""

    epochs: int
    gps_satellite_records: int
    non_gps_satellite_records: int
    boundary_phase_resets: int


@dataclass(frozen=True, slots=True)
class _Header:
    lines: tuple[str, ...]
    gps_codes: tuple[str, ...]
    identity: tuple[tuple[str, str], ...]
    l2c_declaration: tuple[str, ...]


def _read_header(path: Path) -> _Header:
    lines: list[str] = []
    codes: list[str] = []
    identity: dict[str, str] = {}
    comments: list[str] = []
    expected: int | None = None
    active = ""
    gps_phase_unknown = False
    gps_time = False
    native = False
    version_ok = False
    with path.open(encoding="ascii") as stream:
        for raw in stream:
            line = raw.rstrip("\r\n")
            lines.append(line)
            label = line[60:].strip()
            if label == "RINEX VERSION / TYPE":
                if line[:9].strip() != "3.05" or "OBSERVATION DATA" not in line[:60]:
                    raise ValueError("segments must be RINEX 3.05 observations")
                version_ok = True
            if label in _IDENTITY:
                if label in identity:
                    raise ValueError(f"duplicate {label} header")
                identity[label] = line[:60]
            if label == "COMMENT":
                native |= line[:60].startswith("Native RANGE input; GPST epochs")
                if line[:60].startswith("Type-9 L2C attribute supplied"):
                    comments.append(line[:60])
            if label == "SYS / # / OBS TYPES":
                if line[:1].strip():
                    active = line[0]
                    if active == "G":
                        if expected is not None:
                            raise ValueError("duplicate GPS observation header")
                        expected = int(line[3:6])
                if active == "G":
                    codes.extend(line[7:60].split())
            if label == "SYS / PHASE SHIFT" and line[:1] == "G":
                if line[1:60].strip():
                    raise ValueError("merge requires unknown GPS phase alignment")
                gps_phase_unknown = True
            if label == "TIME OF FIRST OBS":
                gps_time = line[48:51] == "GPS"
            if label == "END OF HEADER":
                break
        else:
            raise ValueError("RINEX header is incomplete")
    if (
        not version_ok
        or not native
        or not gps_time
        or not gps_phase_unknown
        or expected is None
        or not codes
        or expected != len(codes)
        or len(set(codes)) != len(codes)
        or any(len(code) != 3 or code[0] not in "CLDS" for code in codes)
        or any(key not in identity for key in _IDENTITY)
    ):
        raise ValueError("unsupported or incomplete um982py GPS observation header")
    return _Header(
        tuple(lines), tuple(codes), tuple(sorted(identity.items())), tuple(comments)
    )


def _epoch(line: str) -> tuple[int, int, int, int, int, Decimal]:
    parts = line[1:].split()
    if len(parts) < 8 or parts[6] != "0":
        raise ValueError("only normal RINEX observation epochs are supported")
    try:
        year, month, day, hour, minute = map(int, parts[:5])
        seconds = Decimal(parts[5])
        datetime(year, month, day, hour, minute)
        if not seconds.is_finite() or not 0 <= seconds < 60:
            raise ValueError("invalid epoch seconds")
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid RINEX epoch") from error
    return year, month, day, hour, minute, seconds


def _header_line(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


def merge_gps_observations(inputs: Sequence[Path], output: Path) -> MergeResult:
    """Merge um982py RANGE exports with unknown phase alignment into GPS RINEX.

    The output is created only after validation. A loss-of-lock flag is set on
    each carrier's first observation after a segment boundary because continuity
    through the interruption has not been established. Other constellations are
    deliberately omitted. Input files must be strictly time ordered.
    """
    if not inputs:
        raise ValueError("at least one segment is required")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    headers = [_read_header(path) for path in inputs]
    if any(
        header.identity != headers[0].identity
        or header.l2c_declaration != headers[0].l2c_declaration
        for header in headers[1:]
    ):
        raise ValueError(
            "station metadata or signal declarations differ between segments"
        )
    codes = tuple(sorted({code for header in headers for code in header.gps_codes}))
    previous: tuple[int, int, int, int, int, Decimal] | None = None
    first: tuple[int, int, int, int, int, Decimal] | None = None
    epochs = gps_count = other_count = resets = 0
    with tempfile.TemporaryFile(mode="w+t", encoding="ascii", newline="") as body:
        for segment_index, (path, header) in enumerate(
            zip(inputs, headers, strict=True)
        ):
            seen_phase: set[tuple[str, str]] = set()
            with path.open(encoding="ascii") as stream:
                for line in stream:
                    if line[60:].strip() == "END OF HEADER":
                        break
                for line in stream:
                    if not line.startswith(">"):
                        raise ValueError("expected RINEX epoch record")
                    moment = _epoch(line)
                    if previous is not None and moment <= previous:
                        raise ValueError("segment epochs overlap or are out of order")
                    previous = moment
                    count = int(line[32:35])
                    if count < 0:
                        raise ValueError("invalid RINEX satellite count")
                    satellites: list[str] = []
                    for _ in range(count):
                        raw = stream.readline()
                        if not raw:
                            raise ValueError("truncated RINEX satellite records")
                        record = raw.rstrip("\r\n")
                        if (
                            len(record) < 3
                            or record[0] not in "GRSECJI"
                            or not record[1:3].isdigit()
                        ):
                            raise ValueError("invalid RINEX satellite record")
                        if record[0] != "G":
                            other_count += 1
                            continue
                        fields = {
                            code: record[3 + 16 * i : 3 + 16 * (i + 1)].ljust(16)
                            for i, code in enumerate(header.gps_codes)
                        }
                        values = []
                        for code in codes:
                            field = fields.get(code, " " * 16)
                            key = (record[:3], code)
                            if (
                                code.startswith("L")
                                and field[:14].strip()
                                and key not in seen_phase
                            ):
                                seen_phase.add(key)
                                if segment_index:
                                    flag = field[14]
                                    if flag not in " 01234567":
                                        raise ValueError(
                                            "invalid RINEX loss-of-lock flag"
                                        )
                                    value = int(flag) if flag.strip() else 0
                                    field = field[:14] + str(value | 1) + field[15:]
                                    resets += 1
                            values.append(field)
                        satellites.append(record[:3] + "".join(values) + "\n")
                    if not satellites:
                        continue
                    if first is None:
                        first = moment
                    body.write(line[:32] + f"{len(satellites):3d}" + line[35:])
                    body.writelines(satellites)
                    epochs += 1
                    gps_count += len(satellites)
        if first is None:
            raise ValueError("segments contain no GPS observations")
        year, month, day, hour, minute, seconds = first
        first_obs = (
            f"{year:6d}{month:6d}{day:6d}{hour:6d}{minute:6d}{seconds:13.7f}     GPS"
        )
        body.seek(0)
        with output.open("x", encoding="ascii", newline="") as destination:
            for line in headers[0].lines:
                label = line[60:].strip()
                if label == "PGM / RUN BY / DATE":
                    created = datetime.now(UTC).strftime("%Y%m%d %H%M%S UTC")
                    destination.write(
                        _header_line(
                            f"{'um982py-merge':<20}{'':20}{created:<20}", label
                        )
                    )
                    destination.write(
                        _header_line(
                            "GPS segments merged with carrier arc resets", "COMMENT"
                        )
                    )
                    continue
                if label in {
                    "SYS / # / OBS TYPES",
                    "SYS / PHASE SHIFT",
                    "GLONASS SLOT / FRQ #",
                    "GLONASS COD/PHS/BIS",
                    "TIME OF LAST OBS",
                }:
                    continue
                if label == "TIME OF FIRST OBS":
                    for start in range(0, len(codes), 13):
                        prefix = f"G  {len(codes):3d}" if start == 0 else "      "
                        destination.write(
                            _header_line(
                                prefix
                                + "".join(
                                    f" {code}" for code in codes[start : start + 13]
                                ),
                                "SYS / # / OBS TYPES",
                            )
                        )
                    destination.write(_header_line("G", "SYS / PHASE SHIFT"))
                    destination.write(_header_line(first_obs, label))
                    continue
                destination.write(line + "\n")
            shutil.copyfileobj(body, destination)
    return MergeResult(epochs, gps_count, other_count, resets)
