"""Unicore log-list parsing."""

from um982py.errors import ProtocolError
from um982py.messages import LogListMessage
from um982py.protocol.ascii import parse_header


def listing_size(buffer: bytearray) -> int | None:
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
        raise ProtocolError("Malformed UNILOGLIST count") from error
    end = second + 1
    for _ in range(count):
        newline = buffer.find(b"\n", end)
        if newline < 0:
            return None
        if not bytes(buffer[end:newline]).lstrip().startswith(b"<"):
            raise ProtocolError("Malformed UNILOGLIST entry")
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
