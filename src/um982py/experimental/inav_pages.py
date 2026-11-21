"""Galileo E1-B I/NAV page capture from receiver memory snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

from um982py.experimental.boot_memory import BootMemoryReader

__all__ = [
    "TRACKING_MEMORY_BASE",
    "TRACKING_MEMORY_LENGTH",
    "InavPage",
    "InavPagePart",
    "InavSnapshot",
    "NmaHeader",
    "NmaStatus",
    "PublicKeyStatus",
    "assemble_osnma_subframe",
    "capture_inav_pages",
    "decode_inav_page_part",
    "extract_inav_pages",
    "parse_nma_header",
]

TRACKING_MEMORY_BASE = 0x318000
"""Base address of the receiver memory window with per-signal tracking state."""

TRACKING_MEMORY_LENGTH = 0xE8000
"""Length of the receiver memory window with per-signal tracking state."""

GALILEO_SIGNAL = 3
"""Signal-family identifier of Galileo channels in the tracking window."""

GALILEO_SVID_BASE = 0x60
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

    @classmethod
    def from_regions(
        cls,
        regions: Mapping[str, tuple[int, bytes]],
        *,
        application_restored: bool | None = None,
    ) -> Self:
        return cls(
            extract_inav_pages(regions),
            {name: content for name, (_, content) in regions.items()},
            application_restored,
        )

    def manifest(self) -> dict[str, object]:
        return {
            "pages": len(self.pages),
            "prns": sorted({page.prn for page in self.pages}),
            "odd_pages": sum(not page.part.even for page in self.pages),
            "pages_with_osnma": sum(page.part.osnma is not None for page in self.pages),
            "regions": {
                name: len(content) for name, content in self.regions.items()
            },
            "application_restored": self.application_restored,
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
                crc=None,
                ssp=None,
            )
        return InavPagePart(
            even=True,
            page_type=1,
            word_type=None,
            data=_slice(page, 2, 112),
            osnma=None,
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
            crc=_slice(page, 82, 24),
            ssp=int(bits[106:114], 2) if len(bits) >= 114 else None,
        )
    return InavPagePart(
        even=False,
        page_type=1,
        word_type=None,
        data=_slice(page, 2, 80),
        osnma=None,
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
                    prn=record[1] - GALILEO_SVID_BASE,
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
    with BootMemoryReader.connect(port, baud, helper=helper) as reader:
        region = reader.read_range(TRACKING_MEMORY_BASE, TRACKING_MEMORY_LENGTH)
    return InavSnapshot.from_regions(
        {"tracking": (TRACKING_MEMORY_BASE, region)},
        application_restored=reader.application_restored,
    )
