"""Galileo E1-B I/NAV page capture from receiver memory snapshots."""

import csv
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from pathlib import Path
from typing import Self

from um982py.experimental.boot_memory import BootMemoryReader
from um982py.experimental.inav_coding import (
    INAV_SYNC_PATTERN,
    bits_of,
    convolutional_decode,
    deinterleave,
    inav_crc24,
    pack_bits,
)

__all__ = [
    "CHANNEL_STATE_WINDOW_OFFSET",
    "TRACKING_MEMORY_BASE",
    "TRACKING_MEMORY_LENGTH",
    "ChannelState",
    "InavPage",
    "InavPagePart",
    "InavSnapshot",
    "InavWord",
    "NmaHeader",
    "NmaStatus",
    "OsnmaSubframe",
    "PageWindowAudit",
    "PublicKeyStatus",
    "SarField",
    "SarLongRlm",
    "SarReplay",
    "SarService",
    "SarShortRlm",
    "WordTiming",
    "assemble_inav_word",
    "assemble_osnma_subframe",
    "assemble_sar_long_rlm",
    "assemble_sar_short_rlm",
    "audit_page_windows",
    "capture_inav_pages",
    "decode_inav_page_part",
    "decode_sar_beacon_id",
    "decode_sar_field",
    "extract_channel_states",
    "extract_inav_pages",
    "osnma_activity",
    "pair_inav_words",
    "parse_nma_header",
    "read_inav_stream_csv",
    "replay_sar_stream",
]

TRACKING_MEMORY_BASE = 0x318000
"""Base address of the receiver memory window with per-signal tracking state."""

TRACKING_MEMORY_LENGTH = 0xE8000
"""Length of the receiver memory window with per-signal tracking state."""

GALILEO_SIGNAL = 3
"""Signal-family identifier of Galileo channels in the tracking window."""

GALILEO_SVID_BASE = 100
"""Offset of the Galileo PRN within the per-signal identifier byte."""

CHANNEL_RECORD_SIZE = 0x148
"""Bytes per per-signal tracking record."""

CHANNEL_STATE_POINTER_OFFSET = 0x134
"""Offset of the page-state pointer within a tracking record."""

STATE_RECORD_SIZE = 0xD0
"""Bytes per page-state record."""

STATE_TIME_OFFSET = 0x04
"""Offset of the time counter within a page-state record."""

PAGE_VALID_FLAG = 0x1000
"""State flag set while the state record holds a checksum-verified page."""

STATE_PAGE_OFFSET = 0x90
"""Offset of the page content within a page-state record."""

STATE_PAGE_LENGTH = 16
"""Bytes of decoded page-part content read from a page-state record."""

OSNMA_FIELD_BITS = 40
"""Bits of OSNMA protocol data carried by every nominal E1-B odd part."""

SAR_FIELD_BITS = 22
"""Bits of search and rescue data carried by every nominal E1-B odd part."""

CHANNEL_STATE_WINDOW_OFFSET = 0x0C
"""Offset of the demodulation window within a page-state record."""

CHANNEL_STATE_WINDOW_LENGTH = 132
"""Bytes of the demodulation window within a page-state record."""


class NmaStatus(StrEnum):
    """Status of the navigation message authentication service."""

    RESERVED = "reserved"
    TEST = "test"
    OPERATIONAL = "operational"
    DO_NOT_USE = "do_not_use"


class PublicKeyStatus(StrEnum):
    """Status of the key chain and public key in force."""

    RESERVED = "reserved"
    NOMINAL = "nominal"
    END_OF_CHAIN = "end_of_chain"
    CHAIN_REVOKED = "chain_revoked"
    NEW_PUBLIC_KEY = "new_public_key"
    PUBLIC_KEY_REVOKED = "public_key_revoked"
    NEW_MERKLE_TREE = "new_merkle_tree"
    ALERT_MESSAGE = "alert_message"


_NMA_STATUS_BY_VALUE = {
    0: NmaStatus.RESERVED,
    1: NmaStatus.TEST,
    2: NmaStatus.OPERATIONAL,
    3: NmaStatus.DO_NOT_USE,
}

_PUBLIC_KEY_STATUS_BY_VALUE = {
    0: PublicKeyStatus.RESERVED,
    1: PublicKeyStatus.NOMINAL,
    2: PublicKeyStatus.END_OF_CHAIN,
    3: PublicKeyStatus.CHAIN_REVOKED,
    4: PublicKeyStatus.NEW_PUBLIC_KEY,
    5: PublicKeyStatus.PUBLIC_KEY_REVOKED,
    6: PublicKeyStatus.NEW_MERKLE_TREE,
    7: PublicKeyStatus.ALERT_MESSAGE,
}


@dataclass(frozen=True, slots=True)
class InavPagePart:
    """One decoded I/NAV page part as broadcast on E1-B.

    Field positions follow the nominal and alert page layouts of the Galileo
    Open Service SIS ICD. Bits are numbered from the most significant bit.
    """

    even: bool
    """Whether the part is the even half of a page."""

    page_type: int
    """Page type bit: 0 for nominal and 1 for alert pages."""

    word_type: int | None
    """Word type of a nominal even part, ``None`` otherwise."""

    data: bytes
    """Data field of the part, right-padded to whole bytes."""

    osnma: bytes | None
    """OSNMA protocol data of a nominal odd part, five bytes, or ``None``."""

    sar: bytes | None
    """Search and rescue data of a nominal odd part, or ``None``."""

    crc: bytes | None
    """Checksum bits of an odd part, three bytes, or ``None``."""

    ssp: int | None
    """Secondary synchronisation pattern of an odd part, or ``None``."""

    @property
    def nominal(self) -> bool:
        """Whether the part belongs to a nominal page."""
        return self.page_type == 0

    @property
    def hkroot_portion(self) -> bytes | None:
        """Eight-bit HKROOT section of the OSNMA field, or ``None``."""
        return None if self.osnma is None else self.osnma[:1]

    @property
    def mack_portion(self) -> bytes | None:
        """Thirty-two-bit MACK section of the OSNMA field, or ``None``."""
        return None if self.osnma is None else self.osnma[1:]

    @property
    def sar_field(self) -> "SarField | None":
        """Decoded search and rescue field, or ``None``."""
        return None if self.sar is None else decode_sar_field(self.sar)


@dataclass(frozen=True, slots=True)
class NmaHeader:
    """Navigation message authentication header of one sub-frame.

    The header opens the HKROOT message and repeats with every sub-frame.
    """

    status: NmaStatus
    """Overall status of the authentication service."""

    chain_id: int
    """Identifier of the key chain in force."""

    public_key_status: PublicKeyStatus
    """Status of the key chain and public key in force."""

    reserved: int
    """Reserved final header bit."""


@dataclass(frozen=True, slots=True)
class InavPage:
    """The most recent decoded E1-B page part of one tracked Galileo signal."""

    svid: int
    """Per-signal identifier as stored by the receiver."""

    prn: int
    """Galileo PRN derived from the per-signal identifier."""

    channel: int
    """Receiver channel number of the tracking record."""

    time_counter: int
    """Per-signal time counter; one value is shared by all signals of a
    snapshot taken while the receiver demodulates a common instant."""

    page_valid: bool
    """Whether the receiver marked the page content as checksum-verified."""

    page: bytes
    """Raw decoded page-part content as stored by the receiver."""

    part: InavPagePart
    """Decoded page-part fields."""


@dataclass(frozen=True, slots=True)
class InavSnapshot:
    """Captured pages together with the memory window they came from."""

    pages: tuple[InavPage, ...]
    regions: Mapping[str, bytes]
    application_restored: bool | None
    """Whether the application responded after the closing reset."""

    capture_started_utc: datetime | None = None
    capture_finished_utc: datetime | None = None
    region_bases: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_regions(
        cls,
        regions: Mapping[str, tuple[int, bytes]],
        *,
        application_restored: bool | None = None,
        capture_started_utc: datetime | None = None,
        capture_finished_utc: datetime | None = None,
    ) -> Self:
        return cls(
            extract_inav_pages(regions),
            {name: content for name, (_, content) in regions.items()},
            application_restored,
            capture_started_utc,
            capture_finished_utc,
            {name: base for name, (base, _) in regions.items()},
        )

    @property
    def memory_windows(self) -> dict[str, tuple[int, bytes]]:
        """Captured regions with their receiver memory base addresses."""
        return {
            name: (self.region_bases.get(name, TRACKING_MEMORY_BASE), data)
            for name, data in self.regions.items()
        }

    def window_audits(self) -> tuple["PageWindowAudit", ...]:
        """Audit only the symbol windows captured in this snapshot."""
        return audit_page_windows(extract_channel_states(self.memory_windows))

    def manifest(self) -> dict[str, object]:
        return {
            "pages": len(self.pages),
            "prns": sorted({page.prn for page in self.pages}),
            "odd_pages": sum(not page.part.even for page in self.pages),
            "pages_with_osnma": sum(page.part.osnma is not None for page in self.pages),
            "regions": {
                name: len(content) for name, content in self.regions.items()
            },
            "region_bases": {
                name: base for name, (base, _) in self.memory_windows.items()
            },
            "application_restored": self.application_restored,
            "capture_started_utc": self.capture_started_utc.isoformat()
            if self.capture_started_utc is not None else None,
            "capture_finished_utc": self.capture_finished_utc.isoformat()
            if self.capture_finished_utc is not None else None,
            "details": [
                {
                    "prn": page.prn,
                    "channel": page.channel,
                    "time_counter": page.time_counter,
                    "page_valid": page.page_valid,
                    "even": page.part.even,
                    "page_type": page.part.page_type,
                    "word_type": page.part.word_type,
                    "page": page.page.hex(),
                    "osnma": page.part.osnma.hex() if page.part.osnma else None,
                    "sar": page.part.sar.hex() if page.part.sar else None,
                    "sar_decoded": _sar_field_manifest(page.part),
                }
                for page in self.pages
            ],
        }


def _bits(data: bytes) -> str:
    return "".join(f"{value:08b}" for value in data)


def _slice(data: bytes, start: int, length: int) -> bytes:
    """Extract ``length`` bits from ``start`` as right-padded bytes."""
    bits = _bits(data)[start : start + length]
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[index : index + 8], 2) for index in range(0, len(bits), 8))


def decode_inav_page_part(page: bytes) -> InavPagePart:
    """Decode one E1-B page part from raw page content.

    Nominal pages follow the E1-B layout of the Galileo Open Service SIS
    ICD: the even part carries the first half of a navigation word, the odd
    part completes the word and carries the OSNMA protocol data, the search
    and rescue data and the page checksum. Alert pages carry reserved data
    in place of the navigation word and, on the odd part, the checksum.
    """
    if not page:
        raise ValueError("Page content is empty")
    bits = _bits(page)
    even = bits[0] == "0"
    page_type = int(bits[1])
    if even:
        if page_type == 0:
            return InavPagePart(
                even=True,
                page_type=0,
                word_type=int(bits[2:8], 2),
                data=_slice(page, 2, 112),
                osnma=None,
                sar=None,
                crc=None,
                ssp=None,
            )
        return InavPagePart(
            even=True,
            page_type=1,
            word_type=None,
            data=_slice(page, 2, 112),
            osnma=None,
            sar=None,
            crc=None,
            ssp=None,
        )
    if page_type == 0:
        return InavPagePart(
            even=False,
            page_type=0,
            word_type=None,
            data=_slice(page, 2, 16),
            osnma=_slice(page, 18, OSNMA_FIELD_BITS),
            sar=_slice(page, 58, SAR_FIELD_BITS),
            crc=_slice(page, 82, 24),
            ssp=int(bits[106:114], 2) if len(bits) >= 114 else None,
        )
    return InavPagePart(
        even=False,
        page_type=1,
        word_type=None,
        data=_slice(page, 2, 80),
        osnma=None,
        sar=None,
        crc=_slice(page, 82, 24),
        ssp=int(bits[106:114], 2) if len(bits) >= 114 else None,
    )


def parse_nma_header(hkroot_portion: bytes) -> NmaHeader:
    """Parse the authentication header that opens the HKROOT message.

    ``hkroot_portion`` is the eight-bit HKROOT section of the OSNMA field of
    the first odd page of a sub-frame, as defined by the Galileo OSNMA SIS
    ICD.
    """
    if len(hkroot_portion) != 1:
        raise ValueError("The header portion is one byte")
    bits = f"{hkroot_portion[0]:08b}"
    return NmaHeader(
        status=_NMA_STATUS_BY_VALUE[int(bits[0:2], 2)],
        chain_id=int(bits[2:4], 2),
        public_key_status=_PUBLIC_KEY_STATUS_BY_VALUE[int(bits[4:7], 2)],
        reserved=int(bits[7]),
    )


@dataclass(frozen=True, slots=True)
class OsnmaSubframe:
    """Assembled OSNMA protocol data of one 30-second sub-frame."""

    hkroot: bytes
    """HKROOT message, 15 bytes."""

    mack: bytes
    """MACK message, 60 bytes."""

    @property
    def header(self) -> NmaHeader:
        """Authentication header at the start of the HKROOT message."""
        return parse_nma_header(self.hkroot[:1])


def assemble_osnma_subframe(osnma_fields: bytes) -> OsnmaSubframe:
    """Concatenate the OSNMA sections of fifteen consecutive odd pages.

    ``osnma_fields`` is the concatenation of the five-byte OSNMA field of
    each odd nominal page of one sub-frame, in transmission order.
    """
    if len(osnma_fields) != 15 * (OSNMA_FIELD_BITS // 8):
        raise ValueError("Fifteen five-byte OSNMA fields are required")
    hkroot = b"".join(
        osnma_fields[index : index + 1]
        for index in range(0, len(osnma_fields), OSNMA_FIELD_BITS // 8)
    )
    mack = b"".join(
        osnma_fields[index + 1 : index + 5]
        for index in range(0, len(osnma_fields), OSNMA_FIELD_BITS // 8)
    )
    return OsnmaSubframe(hkroot, mack)


def extract_inav_pages(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[InavPage, ...]:
    """Collect the stored Galileo pages from one or more memory regions.

    Each entry of ``regions`` maps a name to the base address and content of
    one memory window. Tracking records of Galileo signals are located by
    their signal-family byte and their page-state pointer; the page content
    is read from the state record of every checksum-verified page.
    """
    windows = tuple((base, content) for _, (base, content) in regions.items())

    def window(address: int) -> tuple[int, bytes] | None:
        for base, content in windows:
            if base <= address and address + STATE_RECORD_SIZE <= base + len(content):
                return base, content
        return None

    pages = []
    for _base, content in windows:
        for offset in range(0, max(len(content) - CHANNEL_RECORD_SIZE, 0), 4):
            record = content[offset : offset + CHANNEL_RECORD_SIZE]
            if record[0] != GALILEO_SIGNAL:
                continue
            pointer = int.from_bytes(
                record[
                    CHANNEL_STATE_POINTER_OFFSET : CHANNEL_STATE_POINTER_OFFSET + 4
                ],
                "little",
            )
            target = window(pointer)
            if target is None:
                continue
            state_base, state_content = target
            if not state_base <= pointer < state_base + len(state_content):
                continue
            state = state_content[pointer - state_base :][:STATE_RECORD_SIZE]
            if len(state) < STATE_RECORD_SIZE:
                continue
            prn = record[1] - GALILEO_SVID_BASE
            if not 1 <= prn <= 36:
                continue
            flags = int.from_bytes(state[:4], "little")
            time_counter = int.from_bytes(
                state[STATE_TIME_OFFSET:][:4], "little"
            )
            page = state[STATE_PAGE_OFFSET:][:STATE_PAGE_LENGTH]
            if not any(page):
                continue
            pages.append(
                InavPage(
                    svid=record[1],
                    prn=prn,
                    channel=int.from_bytes(record[4:8], "little"),
                    time_counter=time_counter,
                    page_valid=bool(flags & PAGE_VALID_FLAG),
                    page=bytes(page),
                    part=decode_inav_page_part(bytes(page)),
                )
            )
    return tuple(pages)


def capture_inav_pages(
    port: str,
    *,
    helper: Path,
    baud: int = 921600,
) -> InavSnapshot:
    """Capture the stored Galileo pages of a running receiver.

    The capture reads the tracking window through the boot-menu helper
    protocol. Entering the boot menu pauses the application and the
    demodulator; the returned pages are the parts decoded at that instant.
    No flash write or erase is performed, and the closing reset restarts
    the application from flash.
    """
    started = datetime.now(UTC)
    with BootMemoryReader.connect(port, baud, helper=helper) as reader:
        region = reader.read_range(TRACKING_MEMORY_BASE, TRACKING_MEMORY_LENGTH)
    return InavSnapshot.from_regions(
        {"tracking": (TRACKING_MEMORY_BASE, region)},
        application_restored=reader.application_restored,
        capture_started_utc=started,
        capture_finished_utc=datetime.now(UTC),
    )
@dataclass(frozen=True, slots=True)
class SarField:
    """Search and rescue field of one nominal E1-B odd page part."""

    start: bool
    """True at a possible message start or on a spare field."""

    long_rlm: bool
    """Short or long return-link message identifier of the part."""

    data: bytes
    """Twenty return-link data bits, right-padded to whole bytes."""

    @property
    def data_hex(self) -> str:
        """The twenty data bits as five hexadecimal digits."""
        return self.data.hex()[:5].upper()

    def is_spare_before(self, following: "SarField") -> bool:
        """Check the start bits of two consecutive fields of one satellite."""
        return self.start and following.start


class SarService(StrEnum):
    """Return-link service defined by the Galileo Open Service SIS ICD."""

    ACKNOWLEDGEMENT_TYPE_1 = "acknowledgement_type_1"
    TEST = "test"
    SPARE = "spare"


@dataclass(frozen=True, slots=True)
class SarShortRlm:
    """Short return-link message assembled from four SAR fields."""

    beacon_id: bytes
    """Beacon identification, sixty bits, right-padded to whole bytes."""

    message_code: int
    """Four-bit message code."""

    parameters: bytes
    """Sixteen bits of message parameters, including the parity bit."""

    @property
    def beacon_hex(self) -> str:
        """The beacon identification as its fifteen hexadecimal digits.

        This is the identity format of the 406 MHz distress beacons of
        the Cospas-Sarsat system that Galileo relays and acknowledges.
        """
        return self.beacon_id.hex()[:15].upper()

    @property
    def service(self) -> SarService:
        """Return-link service identified by the code and parameter bits."""
        if self.message_code == 1 and self.parameters[0] >> 6 == 2:
            return SarService.ACKNOWLEDGEMENT_TYPE_1
        if self.message_code == 15:
            return SarService.TEST
        return SarService.SPARE


@dataclass(frozen=True, slots=True)
class SarLongRlm:
    """Long return-link message assembled from eight SAR fields."""

    beacon_id: bytes
    """Beacon identification, sixty bits, right-padded to whole bytes."""

    message_code: int
    """Four-bit message code."""

    parameters: bytes
    """Ninety-six bits of message parameters, including the parity bit."""

    @property
    def beacon_hex(self) -> str:
        """The beacon identification as its fifteen hexadecimal digits."""
        return self.beacon_id.hex()[:15].upper()

    @property
    def service(self) -> SarService:
        """Return-link service. Long-RLM codes are spare in SIS ICD v2.2."""
        return SarService.SPARE


def decode_sar_field(sar: bytes) -> SarField:
    """Decode the twenty-two-bit SAR field of an odd nominal page part.

    The field carries one start bit, the short or long return-link
    message identifier and twenty bits of return-link data, as specified
    by the Open Service SIS ICD.
    """
    if len(sar) != 3:
        raise ValueError("A SAR field occupies three bytes with two padding bits")
    bits = bits_of(sar)[:SAR_FIELD_BITS]
    return SarField(
        start=bits[0] == "1",
        long_rlm=bits[1] == "1",
        data=pack_bits(bits[2:]),
    )


def _sar_field_manifest(part: InavPagePart) -> dict[str, object] | None:
    field = part.sar_field
    if field is None:
        return None
    return {
        "start": field.start,
        "long_rlm": field.long_rlm,
        "data_hex": field.data_hex,
    }


# Cospas-Sarsat T.001 Annex A, Table A3. Each character occupies six bits.
_MODIFIED_BAUDOT = {
    0b111000: "A", 0b110011: "B", 0b101110: "C", 0b110010: "D",
    0b110000: "E", 0b110110: "F", 0b101011: "G", 0b100101: "H",
    0b101100: "I", 0b111010: "J", 0b111110: "K", 0b101001: "L",
    0b100111: "M", 0b100110: "N", 0b100011: "O", 0b101101: "P",
    0b111101: "Q", 0b101010: "R", 0b110100: "S", 0b100001: "T",
    0b111100: "U", 0b101111: "V", 0b111001: "W", 0b110111: "X",
    0b110101: "Y", 0b110001: "Z", 0b100100: " ", 0b011000: "-",
    0b010111: "/", 0b001101: "0", 0b011101: "1", 0b011001: "2",
    0b010000: "3", 0b001010: "4", 0b000001: "5", 0b010101: "6",
    0b011100: "7", 0b001100: "8", 0b000011: "9",
}


def decode_sar_beacon_id(beacon_hex: str) -> dict[str, int | str | None]:
    """Interpret a 15-hex beacon ID under the first-generation T.001 layout.

    The protocol flag precedes a ten-bit country code. User protocol
    codes are three bits wide and location protocol codes are four bits
    wide. For the orbitography protocol, T.006 defines seven characters
    followed by four zero bits. The label is null if that layout fails.
    """
    if len(beacon_hex) != 15 or any(
        digit not in "0123456789ABCDEFabcdef" for digit in beacon_hex
    ):
        raise ValueError("A SAR beacon ID requires exactly fifteen hexadecimal digits")
    bits = f"{int(beacon_hex, 16):060b}"
    user_protocol = bits[0] == "1"
    code = bits[11:14] if user_protocol else bits[11:15]
    decoded: dict[str, int | str | None] = {
        "country_code": int(bits[1:11], 2),
        "protocol_family": "user" if user_protocol else "location",
        "protocol_code_bits": code,
    }
    if user_protocol and code == "000":
        label = "".join(
            _MODIFIED_BAUDOT.get(int(bits[index : index + 6], 2), "?")
            for index in range(14, 56, 6)
        ).lstrip()
        decoded["orbitography_label"] = (
            label if label and "?" not in label and bits[56:] == "0000" else None
        )
    return decoded


def _sar_payload(
    parts: Sequence[SarField], count: int, long_rlm: bool
) -> str | None:
    if len(parts) != count:
        raise ValueError(f"A return-link message needs {count} parts")
    if not parts[0].start or any(part.start for part in parts[1:]):
        return None
    if any(part.long_rlm != long_rlm for part in parts):
        return None
    if any(len(part.data) != 3 for part in parts):
        return None
    payload = "".join(bits_of(part.data)[:20] for part in parts)
    return payload if payload.count("1") % 2 == 0 else None


def assemble_sar_short_rlm(parts: Sequence[SarField]) -> SarShortRlm | None:
    """Assemble a short return-link message from four SAR fields.

    The fields must be consecutive, carry the short identifier and a
    single start bit on the first field, and pass even parity.
    Invalid sequences return ``None``.
    """
    payload = _sar_payload(parts, 4, False)
    if payload is None:
        return None
    return SarShortRlm(
        beacon_id=pack_bits(payload[:60]),
        message_code=int(payload[60:64], 2),
        parameters=pack_bits(payload[64:80]),
    )


def assemble_sar_long_rlm(parts: Sequence[SarField]) -> SarLongRlm | None:
    """Assemble a long return-link message from eight SAR fields.

    The fields must be consecutive, carry the long identifier and a
    single start bit on the first field, and pass even parity.
    Invalid sequences return ``None``.
    """
    payload = _sar_payload(parts, 8, True)
    if payload is None:
        return None
    return SarLongRlm(
        beacon_id=pack_bits(payload[:60]),
        message_code=int(payload[60:64], 2),
        parameters=pack_bits(payload[64:]),
    )


@dataclass(frozen=True, slots=True)
class WordTiming:
    """Time fields of a navigation word."""

    week_number: int
    """Twelve-bit week number."""

    time_of_week: int
    """Twenty-bit time of week, seconds."""

    @property
    def gst_seconds(self) -> int:
        """Galileo system time in seconds of the week."""
        return self.week_number * 604800 + self.time_of_week


@dataclass(frozen=True, slots=True)
class InavWord:
    """One checksum-verified I/NAV navigation word of 128 bits."""

    word_type: int
    """Six-bit navigation word type."""

    content: bytes
    """Full word content, sixteen bytes."""

    iod_nav: int | None
    """Ten-bit issue of data of word types one to four, or ``None``."""

    svid: int | None
    """Satellite identifier of word type four, or ``None``."""

    timing: WordTiming | None
    """Time fields of word type five, or ``None``."""

    @property
    def bits(self) -> str:
        """MSB-first bit string of the word."""
        return bits_of(self.content)

    def manifest(self) -> dict[str, object]:
        return {
            "word_type": self.word_type,
            "content": self.content.hex(),
            "iod_nav": self.iod_nav,
            "svid": self.svid,
            "timing": None
            if self.timing is None
            else {
                "week_number": self.timing.week_number,
                "time_of_week": self.timing.time_of_week,
            },
        }


def assemble_inav_word(even: bytes, odd: bytes) -> InavWord | None:
    """Assemble one nominal page from its two parts and verify the checksum.

    The vertical checksum of the Galileo Open Service SIS ICD covers the
    protected fields of both parts; ``None`` is returned when it does not
    match, which also rejects mismatched part pairs.
    """
    if len(even) < 15 or len(odd) < 15:
        return None
    even_bits = bits_of(even)
    odd_bits = bits_of(odd)
    if even_bits[0] != "0" or odd_bits[0] != "1":
        return None
    if int(even_bits[1]) or int(odd_bits[1]):
        return None
    protected = even_bits[:114] + odd_bits[:82]
    received = int(odd_bits[82:106], 2)
    if inav_crc24(protected) != received:
        return None
    word_bits = even_bits[2:114] + odd_bits[2:18]
    word_type = int(word_bits[:6], 2)
    iod_nav = int(word_bits[6:16], 2) if word_type in (1, 2, 3, 4) else None
    svid = int(word_bits[16:22], 2) if word_type == 4 else None
    timing = None
    if word_type == 5:
        timing = WordTiming(
            week_number=int(word_bits[73:85], 2),
            time_of_week=int(word_bits[85:105], 2),
        )
    return InavWord(
        word_type=word_type,
        content=pack_bits(word_bits),
        iod_nav=iod_nav,
        svid=svid,
        timing=timing,
    )


def pair_inav_words(
    even_parts: Sequence[bytes], odd_parts: Sequence[bytes]
) -> tuple[InavWord, ...]:
    """Assemble all checksum-verified words from candidate part pairs.

    Every even part is combined with every odd part; the page checksum
    accepts exactly the matching pair of one page.
    """
    words = []
    for even in even_parts:
        for odd in odd_parts:
            word = assemble_inav_word(even, odd)
            if word is not None:
                words.append(word)
    return tuple(words)


def read_inav_stream_csv(path: Path) -> dict[int, tuple[bytes, ...]]:
    """Read page parts of one or more satellites from a stream capture.

    The file holds one line per satellite with a decimal SVID and a
    hexadecimal E1-B stream of consecutive 120-bit page parts, the
    format used by the official Galileo OSNMA test vectors.
    """
    streams: dict[int, tuple[bytes, ...]] = {}
    with path.open(encoding="ascii") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None or header[:3] != ["SVID", "NumNavBits", "NavBitsHEX"]:
            raise ValueError("The stream file starts with the SVID header line")
        for row in reader:
            if not row:
                continue
            if len(row) < 3:
                raise ValueError(f"Missing stream fields on line {reader.line_num}")
            svid = int(row[0])
            if svid in streams:
                raise ValueError(f"Duplicate stream for SV {svid:02d}")
            bit_count = int(row[1])
            stream = bytes.fromhex(row[2])
            if bit_count < 0 or bit_count % 120 or bit_count > len(stream) * 8:
                raise ValueError(f"Stream of SV {svid:02d} is not a part sequence")
            parts = tuple(
                stream[index * 15 : (index + 1) * 15]
                for index in range(bit_count // 120)
            )
            streams[svid] = parts
    return streams


@dataclass(frozen=True, slots=True)
class SarReplay:
    """Search and rescue data recovered from one satellite's E1-B stream."""

    crc_checked_fields: int
    spare_fields: int
    messages: tuple[tuple[int, SarShortRlm | SarLongRlm], ...]
    """Pairs of zero-based odd-part index and parity-checked message."""

    def manifest(self) -> dict[str, object]:
        return {
            "crc_checked_fields": self.crc_checked_fields,
            "spare_fields": self.spare_fields,
            "messages": [
                {
                    "start_part_index": index,
                    "length": "long" if isinstance(message, SarLongRlm) else "short",
                    "beacon_hex": message.beacon_hex,
                    "beacon_header": decode_sar_beacon_id(message.beacon_hex),
                    "message_code": message.message_code,
                    "service": message.service.value,
                    "parameters": message.parameters.hex(),
                    "parity_bit": message.parameters[-1] & 1,
                }
                for index, message in self.messages
            ],
        }


def replay_sar_stream(parts: Sequence[bytes]) -> SarReplay:
    """Recover SAR messages from consecutive one-second E1-B page-part slots.

    Keep missing parts as empty bytes. A gap, alert page or failed CRC
    interrupts the sequence. Spare classification needs two consecutive
    CRC-checked fields.
    """
    fields: dict[int, SarField] = {}
    for index, (even, odd) in enumerate(pairwise(parts), start=1):
        if assemble_inav_word(even, odd) is not None:
            field = decode_inav_page_part(odd).sar_field
            if field is not None:
                fields[index] = field

    spare_fields = 0
    messages: list[tuple[int, SarShortRlm | SarLongRlm]] = []
    for index, field in fields.items():
        following = fields.get(index + 2)
        if not field.start or following is None:
            continue
        if field.is_spare_before(following):
            spare_fields += 1
            continue
        count = 8 if field.long_rlm else 4
        window = range(index, index + 2 * count, 2)
        if any(position not in fields for position in window):
            continue
        sequence = [fields[position] for position in window]
        assemble = assemble_sar_long_rlm if field.long_rlm else assemble_sar_short_rlm
        if (message := assemble(sequence)) is not None:
            messages.append((index, message))
    return SarReplay(len(fields), spare_fields, tuple(messages))


def osnma_activity(
    pages: Sequence[InavPage],
) -> dict[str, object]:
    """Summarise the OSNMA presence of captured pages per satellite.

    Satellites that do not transmit OSNMA data send an all-zero OSNMA
    field, so a satellite with any non-zero field is observed to carry
    OSNMA data at the captured instant. Snapshots lack sub-frame
    alignment, so the legacy ``headers`` list is empty.
    """
    odd_pages: dict[int, int] = {}
    nonzero: dict[int, int] = {}
    for page in pages:
        if page.part.osnma is None:
            continue
        odd_pages[page.prn] = odd_pages.get(page.prn, 0) + 1
        if any(page.part.osnma):
            nonzero[page.prn] = nonzero.get(page.prn, 0) + 1
    return {
        "prns": {
            prn: {
                "odd_pages": odd_pages.get(prn, 0),
                "osnma_nonzero": nonzero.get(prn, 0),
                "observed_osnma": nonzero.get(prn, 0) > 0,
                "headers": [],
            }
            for prn in odd_pages
        }
    }


@dataclass(frozen=True, slots=True)
class ChannelState:
    """One per-signal tracking record with its page state, frozen at an instant."""

    prn: int
    """Galileo PRN derived from the per-signal identifier."""

    channel: int
    """Receiver channel number."""

    time_counter: int
    """Per-signal time counter shared by all signals of one instant."""

    record: bytes
    """Raw tracking record bytes."""

    state: bytes
    """Raw page-state record bytes."""


@dataclass(frozen=True, slots=True)
class PageWindowAudit:
    """Independent decode of one receiver demodulation window."""

    prn: int
    """Galileo PRN of the audited signal."""

    sync_offset: int | None
    """Bit offset of the page synchronisation pattern, or ``None``."""

    viterbi_errors: int | None
    """Half-distance of the decoded path, or ``None`` without a sync."""

    tail_valid: bool | None
    """Whether the six tail bits decoded to zero, or ``None``."""

    ssp: int | None
    """Decoded secondary synchronisation pattern, or ``None``."""

    decoded: bytes | None
    """Decoded page-part content, or ``None`` without a sync."""

    def manifest(self) -> dict[str, object]:
        return {
            "prn": self.prn,
            "sync_offset": self.sync_offset,
            "viterbi_errors": self.viterbi_errors,
            "tail_valid": self.tail_valid,
            "ssp": self.ssp,
            "decoded": None if self.decoded is None else self.decoded.hex(),
        }


def extract_channel_states(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[ChannelState, ...]:
    """Collect the per-signal tracking records of a memory snapshot.

    The records are retained unchanged; their measurement fields have no
    verified physical meaning. All records of one snapshot share one
    demodulation instant.
    """
    windows = tuple((base, content) for _, (base, content) in regions.items())

    def window(address: int) -> tuple[int, bytes] | None:
        for base, content in windows:
            if base <= address and address + STATE_RECORD_SIZE <= base + len(content):
                return base, content
        return None

    states = []
    for _base, content in windows:
        for offset in range(0, max(len(content) - CHANNEL_RECORD_SIZE, 0), 4):
            record = content[offset : offset + CHANNEL_RECORD_SIZE]
            if record[0] != GALILEO_SIGNAL:
                continue
            pointer = int.from_bytes(
                record[
                    CHANNEL_STATE_POINTER_OFFSET : CHANNEL_STATE_POINTER_OFFSET + 4
                ],
                "little",
            )
            target = window(pointer)
            if target is None:
                continue
            state_base, state_content = target
            if not state_base <= pointer < state_base + len(state_content):
                continue
            state = state_content[pointer - state_base :][:STATE_RECORD_SIZE]
            if len(state) < STATE_RECORD_SIZE:
                continue
            prn = record[1] - GALILEO_SVID_BASE
            if not 1 <= prn <= 36:
                continue
            states.append(
                ChannelState(
                    prn=prn,
                    channel=int.from_bytes(record[4:8], "little"),
                    time_counter=int.from_bytes(
                        state[STATE_TIME_OFFSET:][:4], "little"
                    ),
                    record=bytes(record),
                    state=bytes(state),
                )
            )
    return tuple(states)


def audit_page_windows(
    states: Sequence[ChannelState],
) -> tuple[PageWindowAudit, ...]:
    """Independently decode the demodulation windows of a snapshot.

    Each page-state record retains the receiver's coded symbol window. The
    audit locates the page synchronisation pattern, de-interleaves the 240
    coded symbols that follow it and decodes them with the convolutional
    code of the Galileo Open Service SIS ICD. The decoded part is judged by
    its own structure: six zero tail bits and, for odd parts, a secondary
    synchronisation pattern. The window advances with reception, so the
    decoded part is the one in flight at the captured instant and is not
    expected to equal the stored page of the same record.
    """
    audits = []
    for state in states:
        window = bits_of(
            state.state[
                CHANNEL_STATE_WINDOW_OFFSET : CHANNEL_STATE_WINDOW_OFFSET
                + CHANNEL_STATE_WINDOW_LENGTH
            ]
        )
        offset = window.find(INAV_SYNC_PATTERN)
        if offset < 0 or offset + 10 + 240 > len(window):
            audits.append(PageWindowAudit(state.prn, None, None, None, None, None))
            continue
        coded = window[offset + 10 : offset + 10 + 240]
        deinterleaved = deinterleave(coded)
        decoded, errors = convolutional_decode(deinterleaved)
        tail_valid = decoded[114:120] == "000000"
        audits.append(
            PageWindowAudit(
                prn=state.prn,
                sync_offset=offset,
                viterbi_errors=errors,
                tail_valid=tail_valid,
                ssp=int(decoded[106:114], 2)
                if decoded[0] == "1" and tail_valid
                else None,
                decoded=pack_bits(decoded[:114]),
            )
        )
    return tuple(audits)


@dataclass(frozen=True, slots=True)
class InavCampaign:
    """Accumulated pages of repeated snapshots of one receiver."""

    snapshots: tuple[InavSnapshot, ...]
    """One snapshot per completed capture cycle."""

    @property
    def pages(self) -> tuple[InavPage, ...]:
        """All captured pages in capture order."""
        return tuple(
            page for snapshot in self.snapshots for page in snapshot.pages
        )

    @property
    def unique_pages(self) -> tuple[InavPage, ...]:
        """Captured pages without byte-identical duplicates per PRN."""
        seen: set[tuple[int, bytes]] = set()
        unique = []
        for page in self.pages:
            key = (page.prn, page.page)
            if key in seen:
                continue
            seen.add(key)
            unique.append(page)
        return tuple(unique)

    @property
    def application_restored(self) -> bool | None:
        """Whether every closing reset returned the application."""
        if self.snapshots and all(
            snapshot.application_restored is None for snapshot in self.snapshots
        ):
            return None
        return all(
            snapshot.application_restored for snapshot in self.snapshots
        )

    def words(self) -> tuple[InavWord, ...]:
        """Assemble checksum-verified words across all snapshots.

        Test each distinct pair of nominal parts of the same PRN once.
        """
        pairs: dict[int, tuple[list[bytes], list[bytes]]] = {}
        for page in self.unique_pages:
            if page.part.nominal:
                even, odd = pairs.setdefault(page.prn, ([], []))
                if page.part.even:
                    even.append(page.page)
                elif page.part.crc is not None:
                    odd.append(page.page)
        return tuple(
            word for prn in sorted(pairs) for word in pair_inav_words(*pairs[prn])
        )

    def manifest(
        self, *, audits: Sequence[Sequence[PageWindowAudit]] | None = None
    ) -> dict[str, object]:
        pages = self.pages
        if audits is None:
            audits = [snapshot.window_audits() for snapshot in self.snapshots]
        return {
            "snapshots": len(self.snapshots),
            "snapshot_details": [
                {"snapshot_index": index, **snapshot.manifest()}
                for index, snapshot in enumerate(self.snapshots, start=1)
            ],
            "pages": len(pages),
            "unique_pages": len(self.unique_pages),
            "prns": sorted({page.prn for page in pages}),
            "words": [word.manifest() for word in self.words()],
            "osnma_activity": osnma_activity(pages),
            "sar_fields": [
                {
                    "prn": page.prn,
                    "channel": page.channel,
                    "time_counter": page.time_counter,
                    "page_valid": page.page_valid,
                    "sar": page.part.sar.hex(),
                    "sar_decoded": _sar_field_manifest(page.part),
                }
                for page in pages
                if page.part.sar is not None
            ],
            "window_audits": [
                {"snapshot_index": index, **audit.manifest()}
                for index, group in enumerate(audits, start=1)
                for audit in group
            ],
            "application_restored": self.application_restored,
        }


def capture_inav_campaign(
    port: str,
    *,
    helper: Path,
    baud: int = 921600,
    snapshots: int = 2,
    pause_seconds: float = 5.0,
    on_snapshot: Callable[[InavSnapshot], None] | None = None,
) -> InavCampaign:
    """Capture several snapshots of the stored Galileo pages.

    Each snapshot enters the boot menu, reads the tracking window and
    resets the application back into navigation. ``pause_seconds`` waits
    between snapshots so the demodulator advances to new page parts; the
    stored part of a channel changes with every completed page. Repeated
    snapshots therefore accumulate the even and odd parts needed for
    checksum-verified word assembly. If given, ``on_snapshot`` runs after
    each completed capture and before the next pause.
    """
    from time import sleep

    if snapshots < 1 or not isfinite(pause_seconds) or pause_seconds < 0:
        raise ValueError(
            "Capture needs at least one snapshot and a finite, nonnegative pause"
        )
    collected = []
    for index in range(snapshots):
        if index:
            sleep(pause_seconds)
        snapshot = capture_inav_pages(port, helper=helper, baud=baud)
        collected.append(snapshot)
        if on_snapshot is not None:
            on_snapshot(snapshot)
    return InavCampaign(tuple(collected))
