"""Galileo HAS message recovery from collected E6-B pages.

The High Accuracy Service spreads each correction message over up to
32 pages of 424 bits, Reed-Solomon encodes them vertically with the
RS(255,32,224) code of the HAS SIS ICD and broadcasts any subset of
the 255 encoded pages. Any ``k`` pages with distinct identifiers
recover the message through the generator-matrix rows of the code.

All field arithmetic, layouts and worked-example values follow the
Galileo HAS SIS ICD, Issue 1.0: the generator polynomial of Table 42
over the Galois field of Table 41, the message page grouping of
section 6.3, the decoding rule of section 6.4 and the complete Annex C
example.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from um982py.experimental.inav_coding import bits_of
from um982py.experimental.native_nav import GalileoHasPage

__all__ = [
    "GALILEO_SIGNALS",
    "GNSS_ID_GALILEO",
    "GNSS_ID_GPS",
    "GPS_SIGNALS",
    "HAS_CODEWORD_PAGES",
    "HAS_INFORMATION_PAGES",
    "HAS_PAGE_BITS",
    "HAS_PAGE_OCTETS",
    "VALIDITY_INTERVALS_S",
    "HasMessage",
    "HasPageSet",
    "Mt1ClockCorrection",
    "Mt1CodeBias",
    "Mt1Header",
    "Mt1MaskBlock",
    "Mt1Message",
    "Mt1OrbitCorrection",
    "Mt1PhaseBias",
    "Mt1SystemMask",
    "collect_has_page_sets",
    "parse_mt1_message",
    "validity_interval_s",
]

GNSS_ID_GPS = 0
GNSS_ID_GALILEO = 2
HAS_PAGE_OCTETS = 53
HAS_PAGE_BITS = 424
HAS_INFORMATION_PAGES = 32
HAS_CODEWORD_PAGES = 255
VALIDITY_INTERVALS_S = (
    5,
    10,
    15,
    20,
    30,
    60,
    90,
    120,
    180,
    240,
    300,
    600,
    900,
    1800,
    3600,
)

GALILEO_SIGNALS = (
    "E1-B I/NAV",
    "E1-C",
    "E1-B + E1-C",
    "E5a-I F/NAV",
    "E5a-Q",
    "E5a-I + E5a-Q",
    "E5b-I I/NAV",
    "E5b-Q",
    "E5b-I + E5b-Q",
    "E5-I",
    "E5-Q",
    "E5-I + E5-Q",
    "E6-B C/NAV",
    "E6-C",
    "E6-B + E6-C",
    "Reserved",
)
GPS_SIGNALS = (
    "L1 C/A",
    "Reserved",
    "Reserved",
    "L1C(D)",
    "L1C(P)",
    "L1C(D+P)",
    "L2 CM",
    "L2 CL",
    "L2 CM+CL",
    "L2 P",
    "Reserved",
    "L5 I",
    "L5 Q",
    "L5 I + L5 Q",
    "Reserved",
    "Reserved",
)

# Primitive polynomial alpha**8 + alpha**4 + alpha**3 + alpha**2 + 1
# of Table 41, Issue 1.0, May 2022.
_FIELD_POLYNOMIAL = 0x11D
_FIELD_ORDER = 0xFF
"""Order of the multiplicative group of the Galois field, 2**8 - 1."""

# Coefficients of the RS(255,32,224) generator polynomial from Table 42,
# low degree first and without its monic leading term.
_GENERATOR_POLYNOMIAL: tuple[int, ...] = (
    88,
    216,
    195,
    23,
    111,
    82,
    79,
    81,
    62,
    120,
    249,
    250,
    11,
    134,
    209,
    116,
    69,
    170,
    208,
    45,
    249,
    223,
    4,
    19,
    120,
    81,
    182,
    217,
    44,
    65,
    93,
    34,
    118,
    227,
    112,
    28,
    65,
    48,
    244,
    165,
    242,
    216,
    121,
    50,
    171,
    32,
    217,
    166,
    133,
    134,
    4,
    120,
    54,
    42,
    13,
    24,
    95,
    228,
    173,
    247,
    80,
    42,
    89,
    68,
    81,
    181,
    112,
    51,
    118,
    108,
    243,
    223,
    18,
    38,
    230,
    1,
    28,
    109,
    131,
    14,
    234,
    151,
    21,
    108,
    7,
    176,
    236,
    147,
    175,
    183,
    66,
    35,
    178,
    243,
    36,
    115,
    255,
    51,
    36,
    6,
    120,
    163,
    59,
    9,
    214,
    102,
    109,
    253,
    152,
    137,
    1,
    144,
    124,
    241,
    143,
    71,
    91,
    227,
    28,
    174,
    13,
    157,
    78,
    20,
    192,
    64,
    130,
    45,
    39,
    46,
    229,
    171,
    193,
    252,
    43,
    165,
    88,
    180,
    179,
    183,
    88,
    99,
    219,
    52,
    210,
    33,
    160,
    146,
    22,
    255,
    111,
    159,
    7,
    237,
    145,
    194,
    68,
    89,
    231,
    201,
    224,
    127,
    5,
    27,
    112,
    71,
    165,
    204,
    236,
    122,
    119,
    49,
    212,
    216,
    151,
    149,
    53,
    249,
    57,
    136,
    85,
    14,
    19,
    128,
    135,
    177,
    179,
    189,
    164,
    98,
    220,
    99,
    241,
    230,
    188,
    170,
    148,
    97,
    121,
    31,
    253,
    134,
    43,
    199,
    81,
    137,
    82,
    54,
    47,
    216,
    172,
    169,
    123,
    246,
    153,
    169,
    32,
    86,
    128,
    83,
    5,
    252,
    251,
)

# Two's-complement sentinels and scales of Tables 25, 31, 37 and 40.
_ORBIT_RADIAL_UNAVAILABLE = 0b1000000000000
_ORBIT_TRACK_UNAVAILABLE = 0b100000000000
_CLOCK_UNAVAILABLE = 0b1000000000000
_CLOCK_DO_NOT_USE = 0b0111111111111
_BIAS_UNAVAILABLE = 0b10000000000
_ORBIT_RADIAL_SCALE_M = 0.0025
_ORBIT_TRACK_SCALE_M = 0.008
_CLOCK_SCALE_M = 0.0025
_CODE_BIAS_SCALE_M = 0.02
_PHASE_BIAS_SCALE_CYCLES = 0.01
_IOD_REF_BITS = {GNSS_ID_GPS: 8, GNSS_ID_GALILEO: 10}
_MT1_HEADER_BITS = 32


def _field_tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Powers and discrete logarithms of the Table 41 Galois field."""
    powers: list[int] = [0] * (2 * _FIELD_ORDER + 2)
    logs: list[int] = [0] * 256
    value = 1
    for power in range(_FIELD_ORDER):
        powers[power] = value
        logs[value] = power
        value <<= 1
        if value & 0x100:
            value ^= _FIELD_POLYNOMIAL
    for power in range(_FIELD_ORDER, 2 * _FIELD_ORDER + 2):
        powers[power] = powers[power - _FIELD_ORDER]
    return tuple(powers), tuple(logs)


_POWERS, _LOGS = _field_tables()


def _gf_multiply(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return _POWERS[_LOGS[left] + _LOGS[right]]


def _gf_inverse(value: int) -> int:
    return _POWERS[_FIELD_ORDER - _LOGS[value]]


def _gf_dot(left: Sequence[int], right: Sequence[int]) -> int:
    total = 0
    for a, b in zip(left, right, strict=True):
        total ^= _gf_multiply(a, b)
    return total


def _residues(count: int) -> tuple[tuple[int, ...], ...]:
    """Generator-matrix columns as residues of x to the 254 - column.

    The systematic matrix keeps the information octets in its first 32
    rows; each parity row reads one coefficient of every column
    residue, at the index given by the page identifier.
    """
    columns: list[list[int]] = [list(_GENERATOR_POLYNOMIAL)]
    for _ in range(HAS_INFORMATION_PAGES - 1):
        top = columns[-1][-1]
        shifted = [0, *columns[-1][:-1]]
        if top:
            for index, coefficient in enumerate(_GENERATOR_POLYNOMIAL):
                shifted[index] ^= _gf_multiply(coefficient, top)
        columns.append(shifted)
    return tuple(tuple(columns[31 - column]) for column in range(count))


def _codeword_row(pid: int, residues: Sequence[Sequence[int]]) -> list[int]:
    """One generator-matrix row for a one-based page identifier."""
    if pid <= HAS_INFORMATION_PAGES:
        return [1 if column == pid - 1 else 0 for column in range(len(residues))]
    return [residue[HAS_CODEWORD_PAGES - pid] for residue in residues]


def _invert(matrix: Sequence[Sequence[int]]) -> list[list[int]] | None:
    """Invert a square matrix over the field, or None when singular."""
    size = len(matrix)
    augmented = [
        [*row, *(1 if index == column else 0 for column in range(size))]
        for index, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = next(
            (row for row in range(column, size) if augmented[row][column]),
            None,
        )
        if pivot is None:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = _gf_inverse(augmented[column][column])
        augmented[column] = [_gf_multiply(value, scale) for value in augmented[column]]
        for row in range(size):
            if row != column and augmented[row][column]:
                factor = augmented[row][column]
                augmented[row] = [
                    value ^ _gf_multiply(factor, other)
                    for value, other in zip(
                        augmented[row], augmented[column], strict=True
                    )
                ]
    return [row[size:] for row in augmented]


def _signed(bits: str) -> int:
    """Two's-complement value of a bit field."""
    value = int(bits, 2)
    return value - (1 << len(bits)) if bits[0] == "1" else value


def validity_interval_s(index: int) -> int | None:
    """Validity interval seconds of a block, None for reserved indexes."""
    return None if index >= len(VALIDITY_INTERVALS_S) else VALIDITY_INTERVALS_S[index]


@dataclass(frozen=True, slots=True)
class Mt1Header:
    """The 32-bit header of an MT1 message."""

    toh_s: int
    """Time of hour of the message information, 0 to 3599 seconds."""

    mask_flag: bool
    orbit_corr_flag: bool
    clock_full_flag: bool
    clock_subset_flag: bool
    code_bias_flag: bool
    phase_bias_flag: bool
    mask_id: int
    """Identity of the mask that the corrections refer to, 0 to 31."""

    iod_set_id: int
    """Identity of the reference set of IODs, 0 to 31."""


@dataclass(frozen=True, slots=True)
class Mt1SystemMask:
    """Satellite, signal and cell masks of one corrected GNSS."""

    gnss_id: int
    satellite_mask: int
    """Forty bits; satellite index 0 is the most significant bit."""

    signal_mask: int
    """Sixteen bits; signal index 0 is the most significant bit."""

    cell_mask_available: bool
    cell_mask: int
    """Cell mask bits, satellite-major; zero when not available."""

    navigation_message_index: int

    @property
    def satellites(self) -> tuple[int, ...]:
        """One-based PRNs or SVIDs of the corrected satellites."""
        return tuple(
            index + 1 for index in range(40) if self.satellite_mask >> (39 - index) & 1
        )

    @property
    def signals(self) -> tuple[int, ...]:
        """Signal indexes of the signals with bias entries."""
        return tuple(
            index for index in range(16) if self.signal_mask >> (15 - index) & 1
        )

    @property
    def cells(self) -> tuple[tuple[int, int], ...]:
        """Satellite and signal pairs for which biases are provided."""
        pairs = [
            (satellite, signal)
            for satellite in self.satellites
            for signal in self.signals
        ]
        if not self.cell_mask_available:
            return tuple(pairs)
        return tuple(
            pair
            for index, pair in enumerate(pairs)
            if self.cell_mask >> (len(pairs) - 1 - index) & 1
        )


@dataclass(frozen=True, slots=True)
class Mt1MaskBlock:
    """The mask block that opens an MT1 message body."""

    systems: tuple[Mt1SystemMask, ...]


@dataclass(frozen=True, slots=True)
class Mt1OrbitCorrection:
    """Radial, along-track and cross-track correction of one satellite."""

    gnss_id: int
    satellite: int
    """One-based PRN or SVID."""

    iod_ref: int
    """Reference issue of data of the corrected orbit and clock."""

    delta_radial_m: float | None
    delta_in_track_m: float | None
    delta_cross_track_m: float | None
    """None where the ICD marks the correction as unavailable."""


@dataclass(frozen=True, slots=True)
class Mt1ClockCorrection:
    """Delta clock correction of one satellite."""

    gnss_id: int
    satellite: int
    delta_clock_m: float | None
    do_not_use: bool
    """Set for the ICD value that orders users to drop the satellite."""


@dataclass(frozen=True, slots=True)
class Mt1CodeBias:
    """Code bias of one satellite signal."""

    gnss_id: int
    satellite: int
    signal: int
    bias_m: float | None


@dataclass(frozen=True, slots=True)
class Mt1PhaseBias:
    """Phase bias and discontinuity indicator of one satellite signal."""

    gnss_id: int
    satellite: int
    signal: int
    bias_cycles: float | None
    discontinuity_indicator: int


@dataclass(frozen=True, slots=True)
class Mt1Message:
    """Parsed header and content blocks of an MT1 message."""

    header: Mt1Header
    mask: Mt1MaskBlock | None
    orbit_validity_index: int | None
    orbits: tuple[Mt1OrbitCorrection, ...] | None
    clock_validity_index: int | None
    clock_multipliers: tuple[int, ...] | None
    clocks: tuple[Mt1ClockCorrection, ...] | None
    code_bias_validity_index: int | None
    code_biases: tuple[Mt1CodeBias, ...] | None
    phase_bias_validity_index: int | None
    phase_biases: tuple[Mt1PhaseBias, ...] | None
    consumed_bits: int
    """Body bits consumed by the parsed blocks."""

    complete: bool
    """Whether the blocks account for every bit of the message content."""

    unsupported: str | None
    """Why parsing stopped early, such as an unsupported block layout."""

    def manifest(self) -> dict[str, object]:
        """Serialise the parsed fields for a report."""
        return {
            "header": {
                "toh_s": self.header.toh_s,
                "mask_flag": self.header.mask_flag,
                "orbit_corr_flag": self.header.orbit_corr_flag,
                "clock_full_flag": self.header.clock_full_flag,
                "clock_subset_flag": self.header.clock_subset_flag,
                "code_bias_flag": self.header.code_bias_flag,
                "phase_bias_flag": self.header.phase_bias_flag,
                "mask_id": self.header.mask_id,
                "iod_set_id": self.header.iod_set_id,
            },
            "mask": None
            if self.mask is None
            else {
                "systems": [
                    {
                        "gnss_id": system.gnss_id,
                        "satellites": system.satellites,
                        "signals": system.signals,
                        "cell_mask_available": system.cell_mask_available,
                        "navigation_message_index": system.navigation_message_index,
                    }
                    for system in self.mask.systems
                ]
            },
            "orbit_validity_s": None
            if self.orbit_validity_index is None
            else validity_interval_s(self.orbit_validity_index),
            "orbits": None if self.orbits is None else len(self.orbits),
            "clock_validity_s": None
            if self.clock_validity_index is None
            else validity_interval_s(self.clock_validity_index),
            "clocks": None if self.clocks is None else len(self.clocks),
            "code_bias_validity_s": None
            if self.code_bias_validity_index is None
            else validity_interval_s(self.code_bias_validity_index),
            "code_biases": None if self.code_biases is None else len(self.code_biases),
            "phase_bias_validity_s": None
            if self.phase_bias_validity_index is None
            else validity_interval_s(self.phase_bias_validity_index),
            "phase_biases": None
            if self.phase_biases is None
            else len(self.phase_biases),
            "consumed_bits": self.consumed_bits,
            "complete": self.complete,
            "unsupported": self.unsupported,
        }


@dataclass(frozen=True, slots=True)
class HasMessage:
    """One recovered HAS message.

    ``octets`` concatenates the ``k`` recovered pages of 424 bits each,
    including the alternating padding appended by the encoder. The
    padding is reported separately so callers keep the raw pages.
    """

    message_type: int
    message_id: int
    message_size: int
    octets: bytes
    padding_bits: int
    consistent: bool
    """Whether every collected page matches the recovered codeword."""

    mt1: Mt1Message | None
    """Parsed MT1 content, None for other message types."""

    @property
    def content_bits(self) -> str:
        """Message content bits without the alternating padding."""
        bits = bits_of(self.octets)
        return bits[: len(bits) - self.padding_bits]

    def manifest(self) -> dict[str, object]:
        """Serialise the recovered message for a report."""
        return {
            "message_type": self.message_type,
            "message_id": self.message_id,
            "message_size": self.message_size,
            "octets": self.octets.hex(),
            "padding_bits": self.padding_bits,
            "consistent": self.consistent,
            "content_bits": len(self.content_bits),
            "mt1": None if self.mt1 is None else self.mt1.manifest(),
        }


@dataclass(frozen=True, slots=True)
class HasPageSet:
    """E6-B pages collected for one message identity.

    Pages from later snapshots replace earlier pages of the same
    identifier, so a long campaign keeps the most recent broadcast.
    """

    message_type: int
    message_id: int
    message_size: int
    """Number of pages that recover the message, one to 32."""

    pages: dict[int, bytes]
    prns: dict[int, int]
    """Transmitting PRN last seen for each page identifier."""

    @property
    def complete(self) -> bool:
        """Whether enough distinct pages are collected."""
        return len(self.pages) >= self.message_size

    def decode(self) -> HasMessage | None:
        """Recover the message from the collected pages.

        Any ``k`` distinct pages solve the codeword; leftover pages
        verify the result and flag mixtures of message instances.
        Returns None while fewer than ``k`` pages are collected.
        """
        size = self.message_size
        if len(self.pages) < size or size > HAS_INFORMATION_PAGES:
            return None
        residues = _residues(size)
        pids = sorted(self.pages)[:size]
        inverse = _invert([_codeword_row(pid, residues) for pid in pids])
        if inverse is None:
            return None
        words = [
            [self.pages[pid][index] for pid in pids] for index in range(HAS_PAGE_OCTETS)
        ]
        columns = [
            [_gf_dot(inverse[row], word) for row in range(size)] for word in words
        ]
        octets = bytes(
            columns[index][row]
            for row in range(size)
            for index in range(HAS_PAGE_OCTETS)
        )
        rows = {pid: _codeword_row(pid, residues) for pid in sorted(self.pages)}
        consistent = all(
            _gf_dot(rows[pid], column) == self.pages[pid][index]
            for pid in sorted(self.pages)
            for index, column in enumerate(columns)
        )
        bits = bits_of(octets)
        mt1 = parse_mt1_message(bits) if self.message_type == 1 else None
        if mt1 is not None and mt1.complete:
            padding = len(bits) - _MT1_HEADER_BITS - mt1.consumed_bits
        else:
            cut = len(bits)
            while cut > 1 and bits[cut - 2] != bits[cut - 1]:
                cut -= 1
            padding = len(bits) - cut
        return HasMessage(
            message_type=self.message_type,
            message_id=self.message_id,
            message_size=size,
            octets=octets,
            padding_bits=padding,
            consistent=consistent,
            mt1=mt1,
        )


def collect_has_page_sets(
    pages: Sequence[GalileoHasPage],
) -> tuple[HasPageSet, ...]:
    """Group non-dummy E6-B pages by message identity.

    Returns one set per observed message type, identifier and size,
    ordered by type and identifier.
    """
    grouped: dict[tuple[int, int, int], tuple[dict[int, bytes], dict[int, int]]] = {}
    for page in pages:
        if page.dummy:
            continue
        if (
            page.message_type is None
            or page.message_id is None
            or page.message_size is None
            or page.page_id is None
        ):
            continue
        identity = (page.message_type, page.message_id, page.message_size)
        page_octets, prns = grouped.setdefault(identity, ({}, {}))
        page_octets[page.page_id] = page.encoded_page
        prns[page.page_id] = page.prn
    return tuple(
        HasPageSet(identity[0], identity[1], identity[2], octets, prns)
        for identity, (octets, prns) in sorted(grouped.items())
    )


def parse_mt1_message(bits: str) -> Mt1Message:
    """Parse the header and content blocks of an MT1 message.

    The blocks follow the flag order: mask, orbit corrections, clock
    full-set corrections, clock subset corrections, code biases and
    phase biases. Parsing stops before unsupported layouts and reports
    the reason, so partially parsed messages never raise.
    """
    if len(bits) < 32:
        return _stopped(
            Mt1Header(
                toh_s=0,
                mask_flag=False,
                orbit_corr_flag=False,
                clock_full_flag=False,
                clock_subset_flag=False,
                code_bias_flag=False,
                phase_bias_flag=False,
                mask_id=0,
                iod_set_id=0,
            ),
            None,
            0,
            "truncated header",
        )
    header = Mt1Header(
        toh_s=int(bits[0:12], 2),
        mask_flag=bits[12] == "1",
        orbit_corr_flag=bits[13] == "1",
        clock_full_flag=bits[14] == "1",
        clock_subset_flag=bits[15] == "1",
        code_bias_flag=bits[16] == "1",
        phase_bias_flag=bits[17] == "1",
        mask_id=int(bits[22:27], 2),
        iod_set_id=int(bits[27:32], 2),
    )
    offset = _MT1_HEADER_BITS
    unsupported: str | None = None

    def take(width: int) -> str | None:
        """Consume the next field, or None when the content ends."""
        nonlocal offset
        if offset + width > len(bits):
            return None
        field = bits[offset : offset + width]
        offset += width
        return field

    mask_block: Mt1MaskBlock | None = None
    if header.mask_flag:
        count_field = take(4)
        count = 16 if count_field is None else int(count_field, 2)
        if count_field is None:
            unsupported = "truncated mask block"
        elif count == 0 or count > 15:
            unsupported = "reserved system count"
        systems: list[Mt1SystemMask] = []
        for _ in range(min(count, 15)):
            gnss_field = take(4)
            satellite_field = take(40)
            signal_field = take(16)
            cell_flag = take(1)
            if (
                gnss_field is None
                or satellite_field is None
                or signal_field is None
                or cell_flag is None
            ):
                unsupported = unsupported or "truncated mask block"
                break
            satellite_mask = int(satellite_field, 2)
            signal_mask = int(signal_field, 2)
            cell_mask = 0
            if cell_flag == "1":
                cell_field = take(
                    (satellite_mask.bit_count()) * (signal_mask.bit_count())
                )
                if cell_field is None:
                    unsupported = unsupported or "truncated mask block"
                    break
                cell_mask = int(cell_field, 2)
            index_field = take(3)
            if index_field is None:
                unsupported = unsupported or "truncated mask block"
                break
            systems.append(
                Mt1SystemMask(
                    gnss_id=int(gnss_field, 2),
                    satellite_mask=satellite_mask,
                    signal_mask=signal_mask,
                    cell_mask_available=cell_flag == "1",
                    cell_mask=cell_mask,
                    navigation_message_index=int(index_field, 2),
                )
            )
        if unsupported is None and take(6) is None:
            unsupported = "truncated mask block"
        mask_block = Mt1MaskBlock(tuple(systems))
    if (
        unsupported is None
        and mask_block is None
        and (
            header.orbit_corr_flag
            or header.clock_full_flag
            or header.code_bias_flag
            or header.phase_bias_flag
        )
    ):
        unsupported = "corrections without a mask block"

    orbits: tuple[Mt1OrbitCorrection, ...] | None = None
    orbit_validity: int | None = None
    if unsupported is None and header.orbit_corr_flag and mask_block:
        validity_field = take(4)
        if validity_field is None:
            unsupported = "truncated orbit block"
        else:
            orbit_validity = int(validity_field, 2)
            corrections: list[Mt1OrbitCorrection] = []
            for system in mask_block.systems:
                length = _IOD_REF_BITS.get(system.gnss_id)
                if length is None:
                    unsupported = f"unsupported GNSS id {system.gnss_id}"
                    break
                truncated = False
                for satellite in system.satellites:
                    iod_field = take(length)
                    radial_field = take(13)
                    in_track_field = take(12)
                    cross_track_field = take(12)
                    if (
                        iod_field is None
                        or radial_field is None
                        or in_track_field is None
                        or cross_track_field is None
                    ):
                        truncated = True
                        break
                    radial = int(radial_field, 2)
                    in_track = int(in_track_field, 2)
                    cross_track = int(cross_track_field, 2)
                    corrections.append(
                        Mt1OrbitCorrection(
                            gnss_id=system.gnss_id,
                            satellite=satellite,
                            iod_ref=int(iod_field, 2),
                            delta_radial_m=None
                            if radial == _ORBIT_RADIAL_UNAVAILABLE
                            else _signed(radial_field) * _ORBIT_RADIAL_SCALE_M,
                            delta_in_track_m=None
                            if in_track == _ORBIT_TRACK_UNAVAILABLE
                            else _signed(in_track_field) * _ORBIT_TRACK_SCALE_M,
                            delta_cross_track_m=None
                            if cross_track == _ORBIT_TRACK_UNAVAILABLE
                            else _signed(cross_track_field) * _ORBIT_TRACK_SCALE_M,
                        )
                    )
                if truncated:
                    unsupported = "truncated orbit block"
                    break
            orbits = tuple(corrections)

    clocks: tuple[Mt1ClockCorrection, ...] | None = None
    clock_validity: int | None = None
    clock_multipliers: tuple[int, ...] | None = None
    if unsupported is None and header.clock_full_flag and mask_block:
        validity_field = take(4)
        if validity_field is None:
            unsupported = "truncated clock block"
        else:
            clock_validity = int(validity_field, 2)
            multipliers: list[int] = []
            truncated = False
            for _ in mask_block.systems:
                multiplier_field = take(2)
                if multiplier_field is None:
                    truncated = True
                    break
                multipliers.append(int(multiplier_field, 2) + 1)
            corrections_clock: list[Mt1ClockCorrection] = []
            if not truncated:
                for position, system in enumerate(mask_block.systems):
                    for satellite in system.satellites:
                        delta_field = take(13)
                        if delta_field is None:
                            truncated = True
                            break
                        delta = int(delta_field, 2)
                        corrections_clock.append(
                            Mt1ClockCorrection(
                                gnss_id=system.gnss_id,
                                satellite=satellite,
                                delta_clock_m=None
                                if delta == _CLOCK_UNAVAILABLE
                                else _signed(delta_field)
                                * _CLOCK_SCALE_M
                                * multipliers[position],
                                do_not_use=delta == _CLOCK_DO_NOT_USE,
                            )
                        )
                    if truncated:
                        break
            if truncated:
                unsupported = "truncated clock block"
            clock_multipliers = tuple(multipliers)
            clocks = tuple(corrections_clock)

    if unsupported is None and header.clock_subset_flag:
        unsupported = "clock subset block"

    code_biases: tuple[Mt1CodeBias, ...] | None = None
    code_validity: int | None = None
    if unsupported is None and header.code_bias_flag and mask_block:
        validity_field = take(4)
        if validity_field is None:
            unsupported = "truncated code bias block"
        else:
            code_validity = int(validity_field, 2)
            biases: list[Mt1CodeBias] = []
            truncated = False
            for system in mask_block.systems:
                for satellite, signal in system.cells:
                    bias_field = take(11)
                    if bias_field is None:
                        truncated = True
                        break
                    bias = int(bias_field, 2)
                    biases.append(
                        Mt1CodeBias(
                            gnss_id=system.gnss_id,
                            satellite=satellite,
                            signal=signal,
                            bias_m=None
                            if bias == _BIAS_UNAVAILABLE
                            else _signed(bias_field) * _CODE_BIAS_SCALE_M,
                        )
                    )
                if truncated:
                    break
            if truncated:
                unsupported = "truncated code bias block"
            code_biases = tuple(biases)

    phase_biases: tuple[Mt1PhaseBias, ...] | None = None
    phase_validity: int | None = None
    if unsupported is None and header.phase_bias_flag and mask_block:
        validity_field = take(4)
        if validity_field is None:
            unsupported = "truncated phase bias block"
        else:
            phase_validity = int(validity_field, 2)
            phase_list: list[Mt1PhaseBias] = []
            truncated = False
            for system in mask_block.systems:
                for satellite, signal in system.cells:
                    bias_field = take(11)
                    indicator_field = take(2)
                    if bias_field is None or indicator_field is None:
                        truncated = True
                        break
                    bias = int(bias_field, 2)
                    phase_list.append(
                        Mt1PhaseBias(
                            gnss_id=system.gnss_id,
                            satellite=satellite,
                            signal=signal,
                            bias_cycles=None
                            if bias == _BIAS_UNAVAILABLE
                            else _signed(bias_field) * _PHASE_BIAS_SCALE_CYCLES,
                            discontinuity_indicator=int(indicator_field, 2),
                        )
                    )
                if truncated:
                    break
            if truncated:
                unsupported = "truncated phase bias block"
            phase_biases = tuple(phase_list)

    return Mt1Message(
        header=header,
        mask=mask_block,
        orbit_validity_index=orbit_validity,
        orbits=orbits,
        clock_validity_index=clock_validity,
        clock_multipliers=clock_multipliers,
        clocks=clocks,
        code_bias_validity_index=code_validity,
        code_biases=code_biases,
        phase_bias_validity_index=phase_validity,
        phase_biases=phase_biases,
        consumed_bits=offset - _MT1_HEADER_BITS,
        complete=(
            unsupported is None
            and offset <= len(bits)
            and len(bits) - offset < HAS_PAGE_BITS
            and _alternating(bits[offset:])
        ),
        unsupported=unsupported,
    )


def _alternating(bits: str) -> bool:
    """Whether every adjacent bit pair differs, as the ICD padding does."""
    return all(left != right for left, right in pairwise(bits))


def _stopped(
    header: Mt1Header,
    mask: Mt1MaskBlock | None,
    consumed_bits: int,
    unsupported: str,
) -> Mt1Message:
    """Assemble the result of a parse that stopped before any block."""
    return Mt1Message(
        header=header,
        mask=mask,
        orbit_validity_index=None,
        orbits=None,
        clock_validity_index=None,
        clock_multipliers=None,
        clocks=None,
        code_bias_validity_index=None,
        code_biases=None,
        phase_bias_validity_index=None,
        phase_biases=None,
        consumed_bits=consumed_bits,
        complete=False,
        unsupported=unsupported,
    )
