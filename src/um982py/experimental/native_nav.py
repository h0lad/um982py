"""Parity-checked navigation from UM982 tracking snapshots."""

from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from itertools import pairwise
from struct import Struct

from um982py.experimental.inav_coding import pack_bits
from um982py.experimental.inav_pages import (
    CHANNEL_RECORD_SIZE,
    CHANNEL_STATE_POINTER_OFFSET,
    GALILEO_SVID_BASE,
    PAGE_VALID_FLAG,
)

__all__ = [
    "BeidouLegacySubframe",
    "GalileoFnavClock",
    "GalileoFnavPage",
    "GalileoHasPage",
    "GlonassFdmaString",
    "GpsLnavSubframe",
    "extract_beidou_nav",
    "extract_galileo_fnav",
    "extract_galileo_has",
    "extract_native_nav",
]

_U32 = Struct("<I")
_GPS_WORDS = Struct("<10I")
_GPS_BLOCK_OFFSET = 0xF4
_NAV_WORD_MASK = (1 << 30) - 1
_GLONASS_STRING_OFFSETS = range(0x28, 0xA0, 12)
_GLONASS_STRING_MASK = (1 << 85) - 1
_BEIDOU_STATE_WORDS = Struct("<107I")
_BEIDOU_PREAMBLE = "11100010010"
_GALILEO_FNAV = 0x13
_GALILEO_E6B = 0x43
_FNAV_WORDS = Struct("<7I")
_GALILEO_PAGE_OFFSET = 0x90
_HAS_WORDS = Struct("<14I")
_HAS_DUMMY_HEADER = 0xAF3BC3
_GALILEO_SVIDS = range(GALILEO_SVID_BASE + 1, GALILEO_SVID_BASE + 37)
_NATIVE_LAYOUTS = {
    0: (range(1, 33), _GPS_BLOCK_OFFSET + _GPS_WORDS.size),
    0x22: (range(161, 224), _BEIDOU_STATE_WORDS.size),
    0x34: (range(65, 89), _GLONASS_STRING_OFFSETS[-1] + 12),
    _GALILEO_FNAV: (
        _GALILEO_SVIDS,
        _GALILEO_PAGE_OFFSET + _FNAV_WORDS.size,
    ),
    _GALILEO_E6B: (_GALILEO_SVIDS, _GALILEO_PAGE_OFFSET + _HAS_WORDS.size),
}

# IS-GPS-200 Table 20-XIV, applied to the 24 data bits after inversion.
_GPS_PARITY_MASKS = (
    0xEC7CD2,
    0x763E69,
    0xBB1F34,
    0x5D8F9A,
    0xAEC7CD,
    0x2DEA27,
)


def _gps_data(word: int, previous: int) -> int | None:
    data = word >> 6
    d29, d30 = previous >> 1 & 1, previous & 1
    if d30:
        data ^= 0xFFFFFF
    parity = 0
    for mask, carry in zip(
        _GPS_PARITY_MASKS, (d29, d30, d29, d30, d30, d29), strict=True
    ):
        parity = (parity << 1) | (((data & mask).bit_count() & 1) ^ carry)
    return data if parity == (word & 63) else None


@dataclass(frozen=True, slots=True)
class GpsLnavSubframe:
    """A stored 300-bit GPS subframe with all ten linked words checked."""

    prn: int
    channel: int
    subframe: int
    next_subframe_tow_s: int
    """The six-second HOW count converted to seconds of GPS week."""

    words: tuple[int, ...]
    """Thirty-bit words in transmission order, including parity."""

    data_words: tuple[int, ...]
    """Twenty-four-bit data words after resolving the inversion rule."""

    def manifest(self) -> dict[str, object]:
        """Return the raw words and their parity-checked data as hex."""
        return {
            "prn": self.prn,
            "channel": self.channel,
            "subframe": self.subframe,
            "next_subframe_tow_s": self.next_subframe_tow_s,
            "words": [f"{word:08x}" for word in self.words],
            "data_words": [f"{word:06x}" for word in self.data_words],
        }


def _gps_subframe(state: memoryview, channel: int, prn: int) -> GpsLnavSubframe | None:
    words = tuple(
        word & _NAV_WORD_MASK
        for word in reversed(_GPS_WORDS.unpack_from(state, _GPS_BLOCK_OFFSET))
    )
    for previous in range(4):
        tlm = _gps_data(words[0], previous)
        if tlm is not None and tlm >> 16 == 0x8B:
            break
    else:
        return None

    decoded = [tlm]
    for previous_word, word in pairwise(words):
        data = _gps_data(word, previous_word)
        if data is None:
            return None
        decoded.append(data)
    how = decoded[1]
    subframe = (how >> 2) & 7
    tow_count = how >> 7
    if not 1 <= subframe <= 5 or tow_count >= 100800:
        return None
    return GpsLnavSubframe(prn, channel, subframe, tow_count * 6, words, tuple(decoded))


# GLONASS FDMA ICD Table 4.13. Each mask includes its own check bit.
# The separate overall check covers all 85 bits.
_GLONASS_CHECK_MASKS = (
    0x0AAAAB55555556AAAD5B01,
    0x0CCCCD9999999B33366D02,
    0x10F0F1E1E1E1E3C3C78E04,
    0x00FF01FE01FE03FC07F008,
    0x1F0001FFFE0003FFF80010,
    0x000001FFFFFFFC00000020,
    0x1FFFFE0000000000000040,
)


@dataclass(frozen=True, slots=True)
class GlonassFdmaString:
    """A stored 85-bit GLONASS string with all Hamming checks satisfied."""

    receiver_svid: int
    channel: int
    string_number: int
    bits: int
    """The 85 bits in transmission order, including Hamming check bits."""

    def manifest(self) -> dict[str, object]:
        """Return the complete string as hex, with three leading pad bits."""
        return {
            "receiver_svid": self.receiver_svid,
            "channel": self.channel,
            "string_number": self.string_number,
            "hex": f"{self.bits:022x}",
        }


def _glonass_strings(
    state: memoryview, channel: int, svid: int
) -> list[GlonassFdmaString]:
    found = []
    seen = set()
    for offset in _GLONASS_STRING_OFFSETS:
        # The native buffer holds the complemented string, low word first.
        value = ~int.from_bytes(state[offset : offset + 12], "little")
        value &= _GLONASS_STRING_MASK
        number = value >> 80
        if (
            not 1 <= number <= 15
            or value in seen
            or value.bit_count() & 1
            or any((value & mask).bit_count() & 1 for mask in _GLONASS_CHECK_MASKS)
        ):
            continue
        seen.add(value)
        found.append(GlonassFdmaString(svid, channel, number, value))
    return found


def _channel_states(
    regions: Mapping[str, tuple[int, bytes]],
    families: tuple[int, ...],
    *,
    channel_limit: int = 256,
) -> Iterator[tuple[int, int, int, memoryview]]:
    windows = [(base, memoryview(data)) for base, data in regions.values()]
    for _, memory in windows:
        for offset in range(0, len(memory) - CHANNEL_RECORD_SIZE + 1, 4):
            family, svid = memory[offset], memory[offset + 1]
            if family not in families:
                continue
            ids, size = _NATIVE_LAYOUTS[family]
            if svid not in ids:
                continue
            channel = _U32.unpack_from(memory, offset + 4)[0]
            pointer = _U32.unpack_from(memory, offset + CHANNEL_STATE_POINTER_OFFSET)[0]
            if channel >= channel_limit or pointer % 4:
                continue
            for base, data in windows:
                start = pointer - base
                if 0 <= start <= len(data) - size:
                    yield family, channel, svid, data[start : start + size]
                    break


def extract_native_nav(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[tuple[GpsLnavSubframe, ...], tuple[GlonassFdmaString, ...]]:
    """Read validated GPS and GLONASS bits from the observed UM982 layout.

    The receiver stores a snapshot of its tracking state. Returned records
    can be stale or duplicated across antenna channels. The output keeps
    native channel IDs and does not combine snapshots into a time series.
    """
    gps = []
    glonass = []
    for family, channel, svid, state in _channel_states(regions, (0, 0x34)):
        if family == 0:
            if (subframe := _gps_subframe(state, channel, svid)) is not None:
                gps.append(subframe)
        else:
            glonass.extend(_glonass_strings(state, channel, svid))
    return tuple(gps), tuple(glonass)


@dataclass(frozen=True, slots=True)
class BeidouLegacySubframe:
    """A stored 300-bit legacy BeiDou subframe with all BCH blocks checked."""

    receiver_svid: int
    channel: int
    subframe: int
    sow_s: int
    words: tuple[int, ...]
    """Ten 30-bit words in transmission order, including parity."""

    data_words: tuple[int, ...]
    """The 26 bits of word 1 and 22 bits per subsequent word."""

    def manifest(self) -> dict[str, object]:
        """Return the raw and deinterleaved data words as hex."""
        return {
            "receiver_svid": self.receiver_svid,
            "channel": self.channel,
            "subframe": self.subframe,
            "sow_s": self.sow_s,
            "words": [f"{word:08x}" for word in self.words],
            "data_words": [
                f"{word:07x}" if index == 0 else f"{word:06x}"
                for index, word in enumerate(self.data_words)
            ],
        }


def _beidou_bch_ok(block: str) -> bool:
    remainder = int(block, 2)
    for bit in range(14, 3, -1):
        if remainder & (1 << bit):
            remainder ^= 0x13 << (bit - 4)
    return remainder == 0


def _beidou_data(bits: str) -> tuple[int, ...] | None:
    # The first 15 bits of word 1 are outside its BCH block.
    if not _beidou_bch_ok(bits[15:30]):
        return None
    data = [int(bits[:26], 2)]
    for start in range(30, 300, 30):
        word = bits[start : start + 30]
        left, right = word[::2], word[1::2]
        if not (_beidou_bch_ok(left) and _beidou_bch_ok(right)):
            return None
        data.append(int(left[:11] + right[:11], 2))
    return tuple(data)


def extract_beidou_nav(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[BeidouLegacySubframe, ...]:
    """Extract complete legacy BeiDou subframes from the native tracking buffer.

    The buffer holds newest words first, packed in 30-bit units. A
    subframe can begin within a unit. The preamble, header and all 19
    BCH blocks are checked before returning the bits.
    """
    found = []
    for _, channel, svid, state in _channel_states(regions, (0x22,)):
        bits = "".join(
            f"{word & _NAV_WORD_MASK:030b}"
            for word in reversed(_BEIDOU_STATE_WORDS.unpack(state))
        )
        index = bits.find(_BEIDOU_PREAMBLE)
        seen = set()
        while 0 <= index <= len(bits) - 300:
            frame = bits[index : index + 300]
            index = bits.find(_BEIDOU_PREAMBLE, index + 1)
            if frame in seen or (decoded := _beidou_data(frame)) is None:
                continue
            subframe = (decoded[0] >> 8) & 7
            sow = ((decoded[0] & 0xFF) << 12) | (decoded[1] >> 10)
            if not 1 <= subframe <= 5 or sow >= 604800 or sow % 3:
                continue
            words = tuple(
                int(frame[start : start + 30], 2) for start in range(0, 300, 30)
            )
            found.append(
                BeidouLegacySubframe(svid, channel, subframe, sow, words, decoded)
            )
            seen.add(frame)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class GalileoFnavClock:
    """Clock and quality fields of a Galileo E5a F/NAV type 1 page."""

    toc_s: int
    af0_s: float
    af1_s_s: float
    af2_s_s2: float
    bgd_e1_e5a_s: float
    sisa_index: int
    e5a_health: int
    e5a_data_validity: int


@dataclass(frozen=True, slots=True)
class GalileoFnavPage:
    """The 214 information bits that the receiver retains after its CRC check."""

    prn: int
    channel: int
    page_type: int
    receiver_time_counter: int
    iod_nav: int | None
    gst_week: int | None
    gst_tow_s: int | None
    clock: GalileoFnavClock | None
    data: bytes
    """The information bits in MSB-first order with two zero padding bits."""

    def manifest(self) -> dict[str, object]:
        """Return the information bits as hex alongside the decoded fields."""
        result = asdict(self)
        result["data"] = self.data.hex()
        return result


def _fnav_field(bits: str, start: int, width: int, *, signed: bool = False) -> int:
    value = int(bits[start : start + width], 2)
    if signed and value >> (width - 1):
        value -= 1 << width
    return value


def extract_galileo_fnav(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[GalileoFnavPage, ...]:
    """Read Galileo E5a F/NAV from the build 25164 tracking state.

    The firmware CRC-checks the received page and saves its information bits
    at state offset 0x90, setting flag 0x1000. The stored data omits the CRC.
    """
    pages = []
    for _, channel, svid, state in _channel_states(
        regions, (_GALILEO_FNAV,), channel_limit=1100
    ):
        if channel == 0 or not _U32.unpack_from(state)[0] & PAGE_VALID_FLAG:
            continue
        words = _FNAV_WORDS.unpack_from(state, _GALILEO_PAGE_OFFSET)
        bits = "".join(f"{word:032b}" for word in words)[:214]
        kind = _fnav_field(bits, 0, 6)
        if kind not in (1, 2, 3, 4, 5, 6, 63):
            continue
        prn = svid - GALILEO_SVID_BASE
        if kind == 1 and _fnav_field(bits, 6, 6) != prn:
            continue

        week_start = {1: 155, 2: 182, 3: 174}.get(kind)
        tow_start = {1: 167, 2: 194, 3: 186, 4: 189}.get(kind)
        tow = _fnav_field(bits, tow_start, 20) if tow_start is not None else None
        if tow is not None and tow >= 604800:
            continue
        clock = None
        if kind == 1:
            clock = GalileoFnavClock(
                toc_s=60 * _fnav_field(bits, 22, 14),
                af0_s=_fnav_field(bits, 36, 31, signed=True) * 2**-34,
                af1_s_s=_fnav_field(bits, 67, 21, signed=True) * 2**-46,
                af2_s_s2=_fnav_field(bits, 88, 6, signed=True) * 2**-59,
                bgd_e1_e5a_s=_fnav_field(bits, 143, 10, signed=True) * 2**-32,
                sisa_index=_fnav_field(bits, 94, 8),
                e5a_health=_fnav_field(bits, 153, 2),
                e5a_data_validity=_fnav_field(bits, 187, 1),
            )
        pages.append(
            GalileoFnavPage(
                prn=prn,
                channel=channel,
                page_type=kind,
                receiver_time_counter=_U32.unpack_from(state, 4)[0],
                iod_nav=_fnav_field(bits, 12 if kind == 1 else 6, 10)
                if kind <= 4
                else None,
                gst_week=_fnav_field(bits, week_start, 12)
                if week_start is not None
                else None,
                gst_tow_s=tow,
                clock=clock,
                data=pack_bits(bits),
            )
        )
    return tuple(pages)


@dataclass(frozen=True, slots=True)
class GalileoHasPage:
    """The 448-bit E6-B HAS page retained after the receiver's C/NAV CRC check."""

    prn: int
    channel: int
    receiver_time_counter: int
    data: bytes
    """Three header bytes followed by 53 Reed-Solomon encoded octets."""

    @property
    def dummy(self) -> bool:
        return int.from_bytes(self.data[:3], "big") == _HAS_DUMMY_HEADER

    @property
    def status(self) -> int | None:
        """Raw HAS Status (HASS) for a non-dummy page."""
        return None if self.dummy else self.data[0] >> 6

    @property
    def message_type(self) -> int | None:
        return None if self.dummy else (self.data[0] >> 2) & 3

    @property
    def message_id(self) -> int | None:
        return None if self.dummy else (self.data[0] & 3) * 8 + (self.data[1] >> 5)

    @property
    def message_size(self) -> int | None:
        return None if self.dummy else (self.data[1] & 31) + 1

    @property
    def page_id(self) -> int | None:
        return None if self.dummy else self.data[2]

    @property
    def encoded_page(self) -> bytes:
        """The 53 encoded octets in transmission order."""
        return self.data[3:]

    def manifest(self) -> dict[str, object]:
        """Serialise the raw page and fields used to collect a message."""
        return {
            "prn": self.prn,
            "channel": self.channel,
            "receiver_time_counter": self.receiver_time_counter,
            "dummy": self.dummy,
            "status": self.status,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "message_size": self.message_size,
            "page_id": self.page_id,
            "data": self.data.hex(),
        }


def extract_galileo_has(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[GalileoHasPage, ...]:
    """Read the retained E6-B HAS pages, including dummy pages.

    Firmware validates the C/NAV checksum and stores the 448-bit HAS
    page that follows the fourteen reserved bits of each C/NAV page.
    The buffer omits the checksum, so replay relies on the valid flag.
    """
    pages = []
    for _, channel, svid, state in _channel_states(
        regions, (_GALILEO_E6B,), channel_limit=1100
    ):
        if channel == 0 or not _U32.unpack_from(state)[0] & PAGE_VALID_FLAG:
            continue
        words = _HAS_WORDS.unpack_from(state, _GALILEO_PAGE_OFFSET)
        data = b"".join(word.to_bytes(4, "big") for word in words)
        if not any(data):
            continue
        pages.append(
            GalileoHasPage(
                svid - GALILEO_SVID_BASE, channel, _U32.unpack_from(state, 4)[0], data
            )
        )
    return tuple(pages)
