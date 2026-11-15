"""Incremental mixed-protocol stream decoding."""

import re
from collections import deque

from um982py.errors import ProtocolError
from um982py.messages.frames import Message, TextLine
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import (
    BINARY_HEADER,
    BINARY_SYNC,
    OEM_BINARY_SYNC,
    parse_binary,
    parse_rtcm,
)
from um982py.protocol.listing import (
    listing_size,
    parse_abbreviated_table,
    parse_listing,
)


class StreamDecoder:
    def __init__(self, *, strict: bool = False, max_frame_size: int = 65_794) -> None:
        if max_frame_size < BINARY_HEADER.size + 4:
            raise ValueError("max_frame_size must be at least 28")
        self.strict = strict
        self.max_frame_size = max_frame_size
        self.errors: deque[ProtocolError] = deque(maxlen=32)
        self.discarded_bytes = 0
        self._buffer = bytearray()

    @property
    def pending(self) -> bytes:
        return bytes(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.errors.clear()
        self.discarded_bytes = 0

    def feed(self, data: bytes) -> tuple[Message, ...]:
        self._buffer.extend(data)
        messages: list[Message] = []
        while self._buffer:
            if self._buffer[0] in (10, 13):
                del self._buffer[0]
                continue
            first = self._buffer[0]
            binary = first == 0xAA
            rtcm = first == 0xD3
            # UNILOGLIST uses a multiline response with its own framing.
            listing = (
                self._buffer.startswith(b"#UNILOGLIST,")
                and b"*" not in self._buffer[: self._buffer.find(b"\n")]
            )
            table = any(
                self._buffer.startswith(b"#" + name + b",")
                for name in (b"LBANDBEAM", b"LBANDTRACKSTATUS")
            )
            if listing or table:
                try:
                    listing_length = listing_size(
                        self._buffer, kind="L-band table" if table else "UNILOGLIST"
                    )
                except ProtocolError as error:
                    self._fail(error, self._buffer.find(b"\n") + 1)
                    continue
                if listing_length is None:
                    if len(self._buffer) > self.max_frame_size:
                        self._fail(
                            ProtocolError("Table exceeds size limit"),
                            len(self._buffer),
                        )
                        continue
                    break
                size = listing_length
            elif binary:
                if len(self._buffer) < 3:
                    break
                if self._buffer[:3] not in (BINARY_SYNC, OEM_BINARY_SYNC):
                    self._discard(1)
                    continue
                if len(self._buffer) < BINARY_HEADER.size:
                    break
                if self._buffer[:3] == OEM_BINARY_SYNC:
                    if self._buffer[3] < 28:
                        self._fail(ProtocolError("Invalid OEM-style header size"), 1)
                        continue
                    size = (
                        self._buffer[3]
                        + int.from_bytes(self._buffer[8:10], "little")
                        + 4
                    )
                else:
                    size = int.from_bytes(self._buffer[6:8], "little") + 28
            elif rtcm:
                if len(self._buffer) < 3:
                    break
                if self._buffer[1] & 0xFC:
                    self._discard(1)
                    continue
                size = ((self._buffer[1] & 3) << 8 | self._buffer[2]) + 6
            else:
                newline = self._buffer.find(b"\n")
                if first not in (ord("$"), ord("#")):
                    starts = [
                        pos
                        for marker in (
                            b"$",
                            b"#",
                            BINARY_SYNC,
                            OEM_BINARY_SYNC,
                            b"\xd3",
                        )
                        if (pos := self._buffer.find(marker)) > 0
                        and (newline < 0 or pos < newline)
                    ]
                    if starts:
                        self._discard(min(starts))
                        continue
                if newline < 0:
                    if len(self._buffer) > self.max_frame_size:
                        self._fail(
                            ProtocolError("ASCII frame exceeds size limit"),
                            self._resync(len(self._buffer)),
                        )
                        continue
                    break
                size = newline + 1
            if size > self.max_frame_size:
                self._fail(
                    ProtocolError("Frame exceeds size limit"), self._resync(size)
                )
                continue
            if len(self._buffer) < size:
                break
            raw = bytes(self._buffer[:size])
            message: Message
            try:
                if listing:
                    message = parse_listing(raw)
                elif table:
                    message = parse_abbreviated_table(raw)
                elif binary:
                    message = parse_binary(raw)
                elif rtcm:
                    message = parse_rtcm(raw)
                else:
                    message = parse_ascii(raw)
            except ProtocolError as error:
                self._fail(error, self._verified_resync(size))
                continue
            del self._buffer[:size]
            messages.append(message)
        return tuple(messages)

    def finish(self) -> None:
        if self._buffer:
            raise ProtocolError(f"Incomplete frame: {len(self._buffer)} pending bytes")

    def _resync(self, limit: int) -> int:
        positions = [
            position
            for marker in (b"$", b"#", b"\xaa", b"\xd3")
            if 0 < (position := self._buffer.find(marker, 1)) < limit
        ]
        return min(positions, default=min(limit, len(self._buffer)))

    def _verified_resync(self, limit: int) -> int:
        # Prefer a complete, checked frame over markers inside corrupt payloads.
        # If none is complete yet, preserve a plausible partial frame: a damaged
        # length may overlap the next frame, independently of read boundaries.
        incomplete = min(limit, len(self._buffer))
        for match in re.finditer(rb"[$#\xaa\xd3]", self._buffer, 0):
            position = match.start()
            if position == 0:
                continue
            candidate = bytes(
                self._buffer[position : position + self.max_frame_size + 1]
            )
            try:
                if candidate.startswith((b"$", b"#")):
                    end = candidate.find(b"\n")
                    if end < 0:
                        if (
                            len(candidate) <= self.max_frame_size
                            and candidate.isascii()
                        ):
                            incomplete = min(incomplete, position)
                        continue
                    if end + 1 > self.max_frame_size:
                        continue
                    if isinstance(parse_ascii(candidate[: end + 1]), TextLine):
                        continue
                elif candidate[0] == 0xAA:
                    if len(candidate) < 3:
                        if any(
                            sync.startswith(candidate)
                            for sync in (BINARY_SYNC, OEM_BINARY_SYNC)
                        ):
                            incomplete = min(incomplete, position)
                        continue
                    if not candidate.startswith((BINARY_SYNC, OEM_BINARY_SYNC)):
                        continue
                    oem = candidate.startswith(OEM_BINARY_SYNC)
                    if oem and len(candidate) >= 4 and candidate[3] < 28:
                        continue
                    if len(candidate) < (28 if oem else BINARY_HEADER.size):
                        incomplete = min(incomplete, position)
                        continue
                    length = (
                        candidate[3] + int.from_bytes(candidate[8:10], "little") + 4
                        if oem
                        else int.from_bytes(candidate[6:8], "little") + 28
                    )
                    if length > self.max_frame_size:
                        continue
                    if len(candidate) < length:
                        incomplete = min(incomplete, position)
                        continue
                    parse_binary(candidate[:length])
                elif candidate[0] == 0xD3:
                    if len(candidate) >= 2 and candidate[1] & 0xFC:
                        continue
                    if len(candidate) < 3:
                        incomplete = min(incomplete, position)
                        continue
                    length = ((candidate[1] & 3) << 8 | candidate[2]) + 6
                    if length > self.max_frame_size:
                        continue
                    if len(candidate) < length:
                        incomplete = min(incomplete, position)
                        continue
                    parse_rtcm(candidate[:length])
                else:
                    continue
            except ProtocolError:
                continue
            return position
        return incomplete

    def _discard(self, count: int) -> None:
        del self._buffer[:count]
        self.discarded_bytes += count

    def _fail(self, error: ProtocolError, count: int) -> None:
        self.errors.append(error)
        self._discard(count)
        if self.strict:
            raise error
