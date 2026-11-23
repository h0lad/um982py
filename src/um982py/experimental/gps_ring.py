"""GPS LNAV subframe history recovered from receiver tracking states.

Tracking states keep the last fifty received L1 C/A navigation words per
channel: one 32-bit slot per 30-bit word, written downward and wrapping.
Each slot holds the word's twenty-four data bits with its two-bit parity
tail, the previous word's two parity bits that link the parity chain, and
the previous word's first four parity bits in the slot's top nibble:

    [prev D25..D28 (4)] [prev D29 D30 (2)] [data (24)] [this D25 D26 (2)]

The parity equations of IS-GPS-200 resolve each word twice over: the
recomputed six parity bits must reproduce the stored tail, and the next
slot must carry the full result in its nibble and top bits. Words
transmitted inverted under the D30 rule resolve from the previous word's
D30, which every slot carries alongside the data.

Slots 33 and above hold the receiver's formatted navigation record
rather than received words. The record carries genuine copies of some
words of the most recent subframes mixed with the receiver's own
bookkeeping, so a subframe is marked clean only when every word comes
from a lower slot. Ephemeris assembly additionally requires the issue of
data clock of subframe 1 to agree with the issue of data of subframes 2
and 3, which rejects the formatted records.

Field layouts follow IS-GPS-200. The ring slot layout, the parity chain
with the D30 resolution, the subframe 2 and 3 field slices and the
subframe 1 identity word were checked against the receiver's console
ephemeris output for matching epochs. Angles are reported in radians,
the receiver's console ephemeris convention.

The subframe 1 clock block is not decoded here: the receiver stores
those words in its formatted navigation record with a non-standard
packing (the group delay word, for instance, lands in a different byte
than the IS-GPS-200 position), so the standard field positions cannot
be applied. Ephemeris assembly therefore carries the identity and the
subframe 2 and 3 fields, and reports the issue of data agreement that
rejects the formatted record copies on live data.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from um982py.experimental.native_nav import (
    _GPS_PARITY_MASKS,
    _channel_states,
)

__all__ = [
    "GPS_RECORD_SLOT_FIRST",
    "GPS_RING_OFFSET",
    "GPS_RING_SLOTS",
    "GpsLnavEphemeris",
    "GpsRingSlot",
    "GpsRingSubframe",
    "assemble_gps_ephemeris",
    "decode_gps_ring_slot",
    "extract_gps_ring_subframes",
]

GPS_RING_OFFSET = 0x18
"""Offset of the navigation word ring within one tracking state."""

GPS_RING_SLOTS = 50
"""Ring capacity: thirty seconds of L1 C/A navigation words."""

GPS_RECORD_SLOT_FIRST = 33
"""First ring slot covered by the receiver's formatted record."""

_PI = 3.141592653589793
_WORD_DATA_MASK = 0xFFFFFF


@dataclass(frozen=True, slots=True)
class GpsRingSlot:
    """One ring slot: a received navigation word plus chain state."""

    data: int
    """Twenty-four data bits as transmitted, before D30 resolution."""

    d25_d26: int
    """Stored first two parity bits of this word."""

    prev_d29_d30: int
    """The previous word's last two parity bits, the chain input."""

    prev_d25_d28: int
    """The previous word's first four parity bits, from the nibble."""

    @property
    def inverted(self) -> bool:
        """Whether this word was transmitted inverted under the D30 rule."""
        return self.prev_d29_d30 & 1 == 1

    @property
    def resolved(self) -> int:
        """The data bits with the D30 inversion resolved."""
        return self.data ^ _WORD_DATA_MASK if self.inverted else self.data


def decode_gps_ring_slot(slot: int) -> GpsRingSlot:
    return GpsRingSlot(
        data=((slot & 0xFFFFFFF) >> 2) & _WORD_DATA_MASK,
        d25_d26=slot & 3,
        prev_d29_d30=(slot & 0xFFFFFFF) >> 26,
        prev_d25_d28=slot >> 28,
    )


def _gps_word_parity(word_data: int, d29: int, d30: int) -> int:
    """Six parity bits of one word, IS-GPS-200 Table 20-XIV."""
    if d30:
        word_data ^= _WORD_DATA_MASK
    parity = 0
    for mask, carry in zip(
        _GPS_PARITY_MASKS, (d29, d30, d29, d30, d30, d29), strict=True
    ):
        parity = (parity << 1) | (((word_data & mask).bit_count() & 1) ^ carry)
    return parity


def _signed(value: int, width: int) -> int:
    return value - (1 << width) if value >> (width - 1) else value


@dataclass(frozen=True, slots=True)
class GpsRingSubframe:
    """One chain-validated L1 C/A subframe recovered from the ring."""

    prn: int
    channel: int
    subframe: int
    next_tow_s: int
    """Time of week at the leading edge of the next subframe, seconds."""

    words: tuple[int, ...]
    """Ten resolved 24-bit data words in transmission order."""

    clean: bool
    """Whether every word came from below the formatted record region."""

    @property
    def overlaid(self) -> bool:
        """Whether any word is covered by the formatted record region."""
        return not self.clean

    def manifest(self) -> dict[str, object]:
        """Serialise the subframe for a report."""
        return {
            "prn": self.prn,
            "channel": self.channel,
            "subframe": self.subframe,
            "next_tow_s": self.next_tow_s,
            "clean": self.clean,
            "words": [f"{word:06x}" for word in self.words],
        }


def _plausible_subframe(subframe: int, words: tuple[int, ...]) -> bool:
    """Reject formatted records that mimic a subframe structure.

    The receiver's formatted record passes the parity chain but its
    bookkeeping words fail the broadcast value ranges.
    """
    if subframe == 1:
        week = words[2] >> 14
        toc = (words[7] >> 16) * 64 + (words[8] >> 18)
        return 0 < week <= 1023 and toc <= 16383
    if subframe == 2:
        eccentricity = ((words[5] & 0xFF) << 24) | words[6]
        sqrt_a = ((words[7] & 0xFF) << 24) | words[8]
        toe = words[9] >> 8
        return (
            eccentricity < (1 << 28)
            and 0x80000000 <= sqrt_a <= 0xC0000000
            and toe <= 37799
        )
    if subframe == 3:
        omega_dot = _signed(words[8], 24)
        idot = _signed((words[9] >> 2) & 0x3FFF, 14)
        return abs(omega_dot) < (1 << 20) and abs(idot) < (1 << 13)
    return True


def _chain_words(slots: list[int], anchor: int) -> tuple[int, ...] | None:
    """Slot ``anchor`` holds the first word. The ring writes downward, so
    later words sit at lower, wrapping slot positions.
    """
    words = []
    for step in range(10):
        slot = slots[(anchor - step) % GPS_RING_SLOTS]
        parts = decode_gps_ring_slot(slot)
        parity = _gps_word_parity(
            parts.data, parts.prev_d29_d30 >> 1, parts.prev_d29_d30 & 1
        )
        if (parity >> 4) & 3 != parts.d25_d26:
            return None
        nxt = decode_gps_ring_slot(slots[(anchor - step - 1) % GPS_RING_SLOTS])
        if nxt.prev_d25_d28 != (parity >> 2) & 0xF:
            return None
        if nxt.prev_d29_d30 != parity & 3:
            return None
        words.append(parts.resolved)
    return tuple(words)


def extract_gps_ring_subframes(
    regions: Mapping[str, tuple[int, bytes]],
) -> tuple[GpsRingSubframe, ...]:
    """Yields the last five subframes per tracked satellite when the ring
    still holds them, marked clean when no word is covered by the
    receiver's formatted record region.
    """
    found = []
    for _, channel, prn, state in _channel_states(regions, (0,)):
        slots = [
            int.from_bytes(bytes(state[GPS_RING_OFFSET + 4 * i :][:4]), "little")
            for i in range(GPS_RING_SLOTS)
        ]
        for anchor in range(GPS_RING_SLOTS):
            words = _chain_words(slots, anchor)
            if words is None or words[0] >> 16 != 0x8B:
                continue
            how = words[1]
            subframe = (how >> 2) & 7
            tow = ((how >> 7) & 0x1FFFF) * 6
            if not 1 <= subframe <= 5 or tow > 604794:
                continue
            if not _plausible_subframe(subframe, words):
                continue
            clean = all(
                (anchor - step) % GPS_RING_SLOTS < GPS_RECORD_SLOT_FIRST
                for step in range(10)
            )
            found.append(
                GpsRingSubframe(
                    prn=prn,
                    channel=channel,
                    subframe=subframe,
                    next_tow_s=tow,
                    words=words,
                    clean=clean,
                )
            )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class GpsLnavEphemeris:
    """A complete L1 C/A ephemeris assembled from clean ring subframes."""

    prn: int
    iodc: int
    iode: int
    week: int
    health: int
    crs_m: float
    crc_m: float
    cuc_rad: float
    cus_rad: float
    cic_rad: float
    cis_rad: float
    delta_n_rad_per_s: float
    m0_rad: float
    eccentricity: float
    sqrt_a_m: float
    toe_s: float
    omega0_rad: float
    i0_rad: float
    omega_rad: float
    omega_dot_rad_per_s: float
    idot_rad_per_s: float

    @property
    def semi_major_axis_m(self) -> float:
        """Semi-major axis of the corrected orbit."""
        return self.sqrt_a_m**2

    def manifest(self) -> dict[str, object]:
        """Serialise the ephemeris for a report."""
        return {
            "prn": self.prn,
            "iodc": self.iodc,
            "iode": self.iode,
            "week": self.week,
            "health": self.health,
            "crs_m": self.crs_m,
            "crc_m": self.crc_m,
            "cuc_rad": self.cuc_rad,
            "cus_rad": self.cus_rad,
            "cic_rad": self.cic_rad,
            "cis_rad": self.cis_rad,
            "delta_n_rad_per_s": self.delta_n_rad_per_s,
            "m0_rad": self.m0_rad,
            "eccentricity": self.eccentricity,
            "sqrt_a_m": self.sqrt_a_m,
            "toe_s": self.toe_s,
            "omega0_rad": self.omega0_rad,
            "i0_rad": self.i0_rad,
            "omega_rad": self.omega_rad,
            "omega_dot_rad_per_s": self.omega_dot_rad_per_s,
            "idot_rad_per_s": self.idot_rad_per_s,
        }


def assemble_gps_ephemeris(
    subframes: Sequence[GpsRingSubframe], prn: int | None = None
) -> GpsLnavEphemeris | None:
    """Requires matching issues of data: the subframe 1 issue of data clock
    reduced to eight bits must equal the subframe 2 and 3 issues of
    data, which the receiver's formatted records fail. Only clean
    subframes qualify. Returns None while any part is missing.
    """
    picked = [subframe for subframe in subframes if prn is None or subframe.prn == prn]
    parts: dict[int, GpsRingSubframe] = {}
    for candidate in picked:
        if not candidate.clean:
            continue
        parts.setdefault(candidate.subframe, candidate)
    if not {1, 2, 3} <= set(parts):
        return None
    sf1, sf2, sf3 = parts[1], parts[2], parts[3]
    if len({sf1.prn, sf2.prn, sf3.prn}) != 1:
        return None
    iode = sf2.words[2] >> 16
    if iode != sf3.words[9] >> 16:
        return None
    iodc = ((sf1.words[2] & 3) << 8) | ((sf1.words[6] >> 8) & 0xFF)
    if iodc & 0xFF != iode:
        return None
    w1, w2, w3 = sf1.words, sf2.words, sf3.words
    return GpsLnavEphemeris(
        prn=sf1.prn,
        iodc=iodc,
        iode=iode,
        week=w1[2] >> 14,
        health=(w1[2] >> 2) & 0x3F,
        crs_m=_signed(w2[2] & 0xFFFF, 16) * 2.0**-5,
        crc_m=_signed(w3[6] >> 8, 16) * 2.0**-5,
        cuc_rad=_signed(w2[5] >> 8, 16) * 2.0**-29,
        cus_rad=_signed(w2[7] >> 8, 16) * 2.0**-29,
        cic_rad=_signed(w3[2] >> 8, 16) * 2.0**-29,
        cis_rad=_signed(w3[4] >> 8, 16) * 2.0**-29,
        delta_n_rad_per_s=_signed(w2[3] >> 8, 16) * 2.0**-43 * _PI,
        m0_rad=_signed((w2[3] & 0xFF) << 24 | w2[4], 32) * 2.0**-31 * _PI,
        eccentricity=(((w2[5] & 0xFF) << 24) | w2[6]) * 2.0**-33,
        sqrt_a_m=(((w2[7] & 0xFF) << 24) | w2[8]) * 2.0**-19,
        toe_s=(w2[9] >> 8) * 16,
        omega0_rad=_signed((w3[2] & 0xFF) << 24 | w3[3], 32) * 2.0**-31 * _PI,
        i0_rad=_signed((w3[4] & 0xFF) << 24 | w3[5], 32) * 2.0**-31 * _PI,
        omega_rad=_signed((w3[6] & 0xFF) << 24 | w3[7], 32) * 2.0**-31 * _PI,
        omega_dot_rad_per_s=_signed(w3[8], 24) * 2.0**-43 * _PI,
        idot_rad_per_s=_signed((w3[9] >> 2) & 0x3FFF, 14) * 2.0**-43 * _PI,
    )
