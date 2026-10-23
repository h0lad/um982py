"""Unicore ASCII and NMEA line parsing."""

import csv
from io import StringIO

from um982py.errors import ChecksumError, ProtocolError
from um982py.messages.frames import (
    AsciiHeader,
    AsciiMessage,
    CommandResponse,
    LegacyAsciiHeader,
    Sentence,
    TextLine,
)
from um982py.protocol.checksums import nmea_checksum, unicore_crc32

_UNCHECKSUMMED_TEXT_PREFIXES = (
    b"$BBNOTICE:",
    b"$PosResult:",
    b"$NAVPOS,",
    b"$NAVVEL,",
    b"$GPSWeekRoll:",
    b"$SIMUTC,",
    b"$AntStatus:",
    b"$PT,",
    b"$PD,",
    b"$PD L6D,",
    b"$PD L6E,",
    b"$SensorADC:",
    b"$AvgSensorADC:",
    b"$SensorADCCheckSumE:",
    b"$MonitorCorAcqChan,",
    b"$BD2IONChErr,",
    b"$MsAjust_",
    b"$ERROR: PosReset",
    b"$Not have Idle Measurement Buffer",
)

_STAR_END_PREFIXES = (
    b"$POSDEBUG,",
    b"$MPTDEBUG,",
    b"$PVTDEBUG,",
    b"$PPPDEBUGMSG,",
    b"$PPPHDEBUGMSG,",
)


def _fields(data: bytes) -> tuple[str, ...]:
    if not data:
        return ()
    return tuple(next(csv.reader(StringIO(data.decode("ascii")), strict=True)))


def parse_ascii(raw: bytes) -> Sentence | AsciiMessage | CommandResponse | TextLine:
    line = raw.rstrip(b"\r\n")
    if not line.startswith((b"$", b"#")):
        return TextLine(raw)
    if b"*" not in line and line.startswith(_UNCHECKSUMMED_TEXT_PREFIXES):
        return TextLine(raw)
    if line.endswith(b"*End") and line.startswith(_STAR_END_PREFIXES):
        return TextLine(raw)
    try:
        body, checksum = line[1:].rsplit(b"*", 1)
        expected = int(checksum, 16)
        if len(checksum) == 2:
            control = line.startswith((b"$command,", b"$CONFIG,", b"#"))
            actual = nmea_checksum(line[:1] + body if control else body)
        elif len(checksum) == 8 and line.startswith((b"#", b"$GPHPD,")):
            actual = unicore_crc32(body)
        else:
            raise ProtocolError("Unsupported ASCII checksum length")
        if expected != actual:
            raise ChecksumError(f"ASCII checksum {expected:x} != {actual:x}")
        if line.startswith(b"$"):
            if body.lower().startswith(b"command,"):
                response = body[len(b"command,") :]
                delimiter = (
                    b",response:" if b",response:" in response else b",response "
                )
                command, status = response.rsplit(delimiter, 1)
                return CommandResponse(
                    command.decode("ascii"), status.decode("ascii").strip(), raw
                )
            name, *sentence_fields = _fields(body)
            return Sentence(name, tuple(sentence_fields), raw)
        head, values = body.split(b";", 1)
        return AsciiMessage(parse_header(head), _fields(values), raw)
    except (ValueError, UnicodeError, csv.Error, StopIteration) as error:
        raise ProtocolError("Malformed ASCII message") from error


def parse_header(head: bytes) -> AsciiHeader | LegacyAsciiHeader:
    try:
        fields = _fields(head)
        if len(fields) >= 2 and fields[1] in ("COM1", "COM2", "COM3"):
            return LegacyAsciiHeader(fields[0], fields[1:])
        if len(fields) != 10:
            raise ProtocolError("Expected ten Unicore ASCII header fields")
        return AsciiHeader(
            fields[0],
            int(fields[1]),
            fields[2],
            fields[3],
            int(fields[4]),
            int(fields[5]),
            int(fields[6]),
            int(fields[7]),
            int(fields[8]),
            int(fields[9]),
        )
    except (ValueError, UnicodeError, csv.Error, StopIteration) as error:
        raise ProtocolError("Malformed ASCII header") from error
