"""Galileo I/NAV reduced clock and ephemeris and FEC2 erasure recovery."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from math import ldexp

from um982py.experimental.inav_coding import GF_EXP, gf_eliminate, gf_multiply
from um982py.experimental.inav_pages import InavWord, WordTiming, assemble_inav_word
from um982py.gnss import WEEK_SECONDS

__all__ = [
    "Fec2Recovery",
    "RedCed",
    "decode_redced",
    "recover_fec2_ced",
    "replay_inav_ced",
]

_GST_CYCLE_SECONDS = 4096 * WEEK_SECONDS
_CED_TYPES = (1, 2, 3, 4)
_PARITY_TYPES = (17, 18, 19, 20)
_FEC2_TYPES = (*_CED_TYPES, *_PARITY_TYPES)
_INFORMATION_OFFSETS = (0, 16, 30, 44, 58)
_PARITY_SIZE = 60


@dataclass(frozen=True, slots=True)
class RedCed:
    """The eight scaled parameters broadcast in Galileo I/NAV word 16."""

    delta_a_m: float
    eccentricity_x: float
    eccentricity_y: float
    delta_i_semicircles: float
    omega0_semicircles: float
    lambda0_semicircles: float
    af0_s: float
    af1_s_per_s: float


def decode_redced(word: InavWord) -> RedCed:
    """Decode word 16 using the signed fields and scales in SIS ICD Table 87."""
    if word.word_type != 16 or len(word.content) != 16 or word.content[0] >> 2 != 16:
        raise ValueError("RedCED requires a 128-bit I/NAV word of type 16")
    # Widths are from Table 52. All fields use two's complement.
    layout = (
        (5, 8),
        (13, -22),
        (13, -22),
        (17, -22),
        (23, -22),
        (23, -22),
        (22, -26),
        (6, -35),
    )
    bits = word.bits
    offset = 6
    values: list[float] = []
    for width, exponent in layout:
        field = bits[offset : offset + width]
        value = int(field, 2)
        if field[0] == "1":
            value -= 1 << width
        values.append(ldexp(value, exponent))
        offset += width
    return RedCed(*values)


def _parity_columns() -> tuple[bytes, ...]:
    # Annex F indexes coefficients in ascending order. The codeword in
    # polynomial order has parity in degrees 0-59 and data in 60-117.
    generator = [1]
    for root in GF_EXP[1 : _PARITY_SIZE + 1]:
        product = [0, *generator]
        for degree, coefficient in enumerate(generator):
            product[degree] ^= gf_multiply(coefficient, root)
        generator = product

    # The column for data octet i is the remainder of x**(60 + i).
    first = generator[:-1]
    remainder = first
    columns = []
    for _ in range(_INFORMATION_OFFSETS[-1]):
        columns.append(bytes(remainder))
        leading = remainder[-1]
        remainder = [0, *remainder[:-1]]
        if leading:
            for degree, coefficient in enumerate(first):
                remainder[degree] ^= gf_multiply(coefficient, leading)
    return tuple(columns)


_PARITY_COLUMNS = _parity_columns()


def _solve_erasures(rows: list[list[int]], count: int) -> list[int] | None:
    """Eliminate the erased octets and check all surplus parity equations."""
    if not gf_eliminate(rows, count) or any(row[-1] for row in rows[count:]):
        return None
    return [row[-1] for row in rows[:count]]


@dataclass(frozen=True, slots=True)
class Fec2Recovery:
    """A coherent FEC2 clock and ephemeris block."""

    iod_nav: int
    words: tuple[bytes, ...]
    """Full 128-bit words in type order 1 to 4."""

    recovered_types: tuple[int, ...]
    """Word types reconstructed from parity instead of received directly."""


def recover_fec2_ced(words: Mapping[int, InavWord]) -> Fec2Recovery | None:
    """Supply any coherent combination of types 1-4 and 17-20. Parity provides
    only two bits of IODnav, so callers must associate words by transmission
    context. Recovery needs enough parity octets to solve the missing octets.
    Extra parity equations and the available issue bits are checked before
    returning. The decoder treats missing words as erasures.
    """
    information: list[int | None] = [None] * _INFORMATION_OFFSETS[-1]
    parity: dict[int, int] = {}
    data_issues: set[int] = set()
    parity_issues: set[int] = set()
    for word_type in _FEC2_TYPES:
        word = words.get(word_type)
        if word is None:
            continue
        content = word.content
        if (
            word.word_type != word_type
            or len(content) != 16
            or content[0] >> 2 != word_type
        ):
            raise ValueError(f"Invalid I/NAV word type {word_type}")
        if word_type in _CED_TYPES:
            iod = int.from_bytes(content[:2], "big") & 0x3FF
            data_issues.add(iod)
            start, end = _INFORMATION_OFFSETS[word_type - 1 : word_type + 1]
            information[max(2, start) : end] = list(content[2:])
        else:
            parity_issues.add(content[1] & 3)
            octets = bytes(((int.from_bytes(content[:2], "big") >> 2) & 0xFF,))
            start = (word_type - 17) * 15
            parity.update(enumerate(octets + content[2:], start))

    if len(data_issues) > 1 or len(parity_issues) != 1:
        return None
    (issue_lsb,) = parity_issues
    if data_issues and next(iter(data_issues)) & 3 != issue_lsb:
        return None
    # The transformed WT1 header contains a constant type and the issue.
    # Use any bits already supplied by the other CED and parity words.
    information[0] = 4 | issue_lsb
    if data_issues:
        information[1] = next(iter(data_issues)) >> 2
    erased = [index for index, value in enumerate(information) if value is None]
    if len(erased) > len(parity):
        return None
    rows = []
    known = [(i, value) for i, value in enumerate(information) if value]
    for index, symbol in parity.items():
        for position, value in known:
            symbol ^= gf_multiply(_PARITY_COLUMNS[position][index], value)
        rows.append([*(_PARITY_COLUMNS[pos][index] for pos in erased), symbol])
    recovered = _solve_erasures(rows, len(erased))
    if recovered is None:
        return None
    for position, value in zip(erased, recovered, strict=True):
        information[position] = value
    data = bytes(value or 0 for value in information)
    iod = (data[1] << 2) | issue_lsb
    return Fec2Recovery(
        iod_nav=iod,
        words=tuple(
            ((word_type << 10) | iod).to_bytes(2, "big")
            + data[
                max(2, _INFORMATION_OFFSETS[word_type - 1]) : _INFORMATION_OFFSETS[
                    word_type
                ]
            ]
            for word_type in _CED_TYPES
        ),
        recovered_types=tuple(
            word_type for word_type in _CED_TYPES if word_type not in words
        ),
    )


def replay_inav_ced(parts: Sequence[bytes]) -> dict[str, object]:
    """Inspect one satellite's CRC-checked E1-B stream for RedCED and FEC2.

    Parts occupy consecutive one-second slots, with empty bytes for
    missing parts. A consistent WT5 timing anchor allows FEC2 grouping
    within each GST sub-frame and gives the RedCED reference time.
    """
    words = [
        (index, word)
        for index, (even, odd) in enumerate(pairwise(parts))
        if (word := assemble_inav_word(even, odd)) is not None
    ]
    origins = {
        (word.timing.gst_seconds - index) % _GST_CYCLE_SECONDS
        for index, word in words
        if word.timing is not None
        and 0 <= word.timing.time_of_week < WEEK_SECONDS
        and word.timing.time_of_week % 2 == 1
    }
    origin = next(iter(origins)) if len(origins) == 1 else None
    reduced = []
    frames: dict[int, dict[int, InavWord]] = {}
    conflicts: set[int] = set()
    for index, word in words:
        gst = None if origin is None else (origin + index) % _GST_CYCLE_SECONDS
        frame_start = None if gst is None else gst - gst % 30
        if word.word_type == 16:
            reference = None
            if frame_start is not None:
                reference = WordTiming(*divmod(frame_start + 1, WEEK_SECONDS))
            reduced.append(
                {
                    "even_part_index": index,
                    "word": word.content.hex(),
                    "reference_time": None if reference is None else asdict(reference),
                    "parameters": asdict(decode_redced(word)),
                }
            )
        elif frame_start is not None and word.word_type in _FEC2_TYPES:
            frame = frames.setdefault(frame_start, {})
            existing = frame.get(word.word_type)
            if existing is not None and existing.content != word.content:
                conflicts.add(frame_start)
            frame[word.word_type] = word

    fec2 = []
    for start, frame in frames.items():
        if start in conflicts or (result := recover_fec2_ced(frame)) is None:
            continue
        fec2.append(
            {
                "subframe_time": asdict(WordTiming(*divmod(start, WEEK_SECONDS))),
                "iod_nav": result.iod_nav,
                "recovered_types": result.recovered_types,
                "words": [word.hex() for word in result.words],
            }
        )
    return {"redced": reduced, "fec2": fec2}
