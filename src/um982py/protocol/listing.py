"""Unicore log-list and abbreviated table parsing."""

import csv
from io import StringIO

from um982py.errors import ProtocolError
from um982py.messages import AbbreviatedAsciiMessage, LogListMessage
from um982py.protocol.ascii import parse_header


def listing_size(buffer: bytearray, *, kind: str = "UNILOGLIST") -> int | None:
    first = buffer.find(b"\n")
    second = buffer.find(b"\n", first + 1)
    if first < 0 or second < 0:
        return None
    try:
        count_line = bytes(buffer[first + 1 : second]).strip()
        if not count_line.startswith(b"<"):
            raise ValueError("Missing log count")
        count = int(count_line[1:].strip())
        if not 0 <= count <= 30:
            raise ValueError("Invalid log count")
    except ValueError as error:
        raise ProtocolError(f"Malformed {kind} count") from error
    end = second + 1
    for _ in range(count):
        newline = buffer.find(b"\n", end)
        if newline < 0:
            return None
        if not bytes(buffer[end:newline]).lstrip().startswith(b"<"):
            raise ProtocolError(f"Malformed {kind} entry")
        end = newline + 1
    return end


def parse_listing(raw: bytes) -> LogListMessage:
    lines = raw.splitlines()
    head = lines[0].removeprefix(b"#").removesuffix(b";")
    try:
        entries = tuple(
            line.lstrip(b"<\t ").decode("ascii").strip() for line in lines[2:]
        )
    except UnicodeError as error:
        raise ProtocolError("UNILOGLIST entries must be ASCII") from error
    return LogListMessage(parse_header(head), entries, raw)


def parse_abbreviated_table(raw: bytes) -> AbbreviatedAsciiMessage:
    """Read a count and CSV rows from an unchecksummed L-band table."""
    lines = raw.splitlines()
    try:
        if not lines[0].startswith(b"#") or not lines[0].endswith(b";"):
            raise ProtocolError("Malformed abbreviated table header")
        head = lines[0][1:-1]
        fields = [lines[1].lstrip(b"<\t ").decode("ascii").strip()]
        for line in lines[2:]:
            row = line.lstrip(b"<\t ").decode("ascii").strip()
            fields.extend(next(csv.reader(StringIO(row), strict=True)))
        return AbbreviatedAsciiMessage(parse_header(head), tuple(fields), raw)
    except (UnicodeError, csv.Error, StopIteration, IndexError) as error:
        raise ProtocolError("Malformed abbreviated table") from error
