"""Parity-checked GPS and GLONASS navigation from UM982 tracking snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from struct import Struct

from um982py.experimental.inav_pages import (
    CHANNEL_RECORD_SIZE,
    CHANNEL_STATE_POINTER_OFFSET,
)

__all__ = ["GlonassFdmaString", "GpsLnavSubframe", "extract_native_nav"]

_U32 = Struct("<I")
_GPS_WORDS = Struct("<10I")
_GPS_BLOCK_OFFSET = 0xF4
_GPS_WORD_MASK = (1 << 30) - 1
_GLONASS_STRING_OFFSETS = range(0x28, 0xA0, 12)
_GLONASS_STRING_MASK = (1 << 85) - 1

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
        word & _GPS_WORD_MASK
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


def extract_native_nav(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[tuple[GpsLnavSubframe, ...], tuple[GlonassFdmaString, ...]]:
    """Read validated GPS and GLONASS bits from the observed UM982 layout.

    The receiver stores a snapshot of its tracking state. Returned records
    can be stale or duplicated across antenna channels. The output keeps
    native channel IDs and does not combine snapshots into a time series.
    """
    windows = [(base, memoryview(data)) for base, data in regions.values()]
    gps = []
    glonass = []
    for _, memory in windows:
        for offset in range(0, len(memory) - CHANNEL_RECORD_SIZE + 1, 4):
            family, svid = memory[offset], memory[offset + 1]
            if family == 0 and 1 <= svid <= 32:
                size = _GPS_BLOCK_OFFSET + _GPS_WORDS.size
            elif family == 0x34 and 65 <= svid <= 88:
                size = _GLONASS_STRING_OFFSETS[-1] + 12
            else:
                continue
            channel = _U32.unpack_from(memory, offset + 4)[0]
            pointer = _U32.unpack_from(memory, offset + CHANNEL_STATE_POINTER_OFFSET)[0]
            if channel >= 256 or pointer % 4:
                continue
            for base, data in windows:
                start = pointer - base
                if not 0 <= start <= len(data) - size:
                    continue
                state = data[start : start + size]
                if family == 0:
                    if (subframe := _gps_subframe(state, channel, svid)) is not None:
                        gps.append(subframe)
                else:
                    glonass.extend(_glonass_strings(state, channel, svid))
                break
    return tuple(gps), tuple(glonass)
