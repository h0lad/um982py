"""I/NAV channel coding: CRC-24, interleaving and convolutional coding."""

import binascii

__all__ = [
    "CONVOLUTIONAL_G1",
    "CONVOLUTIONAL_G2",
    "INAV_CRC_POLYNOMIAL",
    "INAV_SYNC_PATTERN",
    "SSP_PATTERNS",
    "bits_of",
    "convolutional_decode",
    "convolutional_encode",
    "deinterleave",
    "inav_crc24",
    "interleave",
    "pack_bits",
    "slice_bits",
]

INAV_SYNC_PATTERN = "0101100000"
"""Ten-bit page synchronisation pattern, not covered by the FEC."""

INAV_CRC_POLYNOMIAL = 0x1864CFB
"""Generator G(X) = (1 + X)P(X) of the I/NAV checksum."""

SSP_PATTERNS = {
    "SSP1": 0b00000100,
    "SSP2": 0b00101011,
    "SSP3": 0b00101111,
}
"""The three secondary synchronisation pattern configurations."""

CONVOLUTIONAL_G1 = 0o171
"""First generator polynomial of the rate one-half convolutional code."""

CONVOLUTIONAL_G2 = 0o133
"""Second generator polynomial of the rate one-half convolutional code."""

INTERLEAVER_COLUMNS = 30
"""Number of columns of the I/NAV block interleaver."""

INTERLEAVER_ROWS = 8
"""Number of rows of the I/NAV block interleaver."""


def bits_of(data: bytes) -> str:
    """Return the MSB-first bit string of ``data``."""
    return "".join(f"{value:08b}" for value in data)


def pack_bits(bitstring: str) -> bytes:
    """Pack an MSB-first bit string into bytes, right-padded with zeros."""
    padded = bitstring + "0" * (-len(bitstring) % 8)
    return bytes(
        int(padded[index : index + 8], 2) for index in range(0, len(padded), 8)
    )


def slice_bits(data: bytes, start: int, length: int) -> str:
    """Return ``length`` bits of ``data`` starting at MSB-first bit ``start``."""
    return bits_of(data)[start : start + length]


def inav_crc24(bitstring: str) -> int:
    """Return the 24 I/NAV checksum bits of an MSB-first bit string.

    The checksum follows the Galileo Open Service SIS ICD: the remainder of
    the binary polynomial division of the information polynomial shifted by
    24 positions, using G(X) = (1 + X)P(X).
    """
    register = 0
    for bit in bitstring + "0" * 24:
        top = register >> 23 & 1
        register = (register << 1 | (bit == "1")) & 0xFFFFFF
        if top:
            register ^= INAV_CRC_POLYNOMIAL & 0xFFFFFF
    return register


def interleave(bitstring: str) -> str:
    """Return the I/NAV block-interleaved symbol stream.

    Symbols are written into 30 columns of 8 symbols and read out row by
    row, as specified for the I/NAV message.
    """
    columns = [
        bitstring[column * INTERLEAVER_ROWS : (column + 1) * INTERLEAVER_ROWS]
        for column in range(INTERLEAVER_COLUMNS)
    ]
    return "".join(
        columns[column][row]
        for row in range(INTERLEAVER_ROWS)
        for column in range(INTERLEAVER_COLUMNS)
    )


def deinterleave(bitstring: str) -> str:
    """Return the symbol stream before I/NAV block interleaving.

    This is the inverse of :func:`interleave`: symbols are written into
    8 rows of 30 symbols and read out column by column.
    """
    rows = [
        bitstring[row * INTERLEAVER_COLUMNS : (row + 1) * INTERLEAVER_COLUMNS]
        for row in range(INTERLEAVER_ROWS)
    ]
    return "".join(
        rows[row][column]
        for column in range(INTERLEAVER_COLUMNS)
        for row in range(INTERLEAVER_ROWS)
    )


def _branch(register: int, polynomial: int) -> int:
    value = register & polynomial
    parity = 0
    while value:
        parity ^= value & 1
        value >>= 1
    return parity


def convolutional_encode(bitstring: str) -> str:
    """Return the rate one-half coded symbol stream of ``bitstring``.

    The first symbol of each pair uses G1, the second G2 with the output
    inverted at the end of the branch, as specified for the Galileo
    navigation messages.
    """
    register = 0
    output = []
    for bit in bitstring:
        register = ((register << 1) | (bit == "1")) & 0x7F
        output.append(_branch(register, CONVOLUTIONAL_G1))
        output.append(_branch(register, CONVOLUTIONAL_G2) ^ 1)
    return "".join(str(value) for value in output)


def convolutional_decode(coded: str) -> tuple[str, int]:
    """Hard-decision Viterbi decode of a coded symbol stream.

    Returns the decoded bit string and the number of half-distance steps of
    the best path. A zero-error result reproduces the encoded input exactly.
    """
    if len(coded) % 2:
        raise ValueError("Coded stream must contain symbol pairs")
    costs = [1 << 30] * 64
    costs[0] = 0
    paths: list[list[int]] = [[] for _ in range(64)]
    for index in range(0, len(coded), 2):
        first = coded[index] == "1"
        second = coded[index + 1] == "1"
        next_costs = [1 << 30] * 64
        next_paths: list[list[int] | None] = [None] * 64
        for state in range(64):
            cost = costs[state]
            if cost == 1 << 30:
                continue
            for bit in (0, 1):
                register = (state << 1 | bit) & 0x7F
                expected_second = _branch(register, CONVOLUTIONAL_G2) ^ 1
                distance = (
                    (first != bool(_branch(register, CONVOLUTIONAL_G1)))
                    + (second != bool(expected_second))
                )
                candidate = cost + distance
                target = register & 0x3F
                if candidate < next_costs[target]:
                    next_costs[target] = candidate
                    next_paths[target] = paths[state] + [bit]
        costs = next_costs
        paths = [path if path is not None else [] for path in next_paths]
    best = min(range(64), key=lambda state: costs[state])
    return "".join(str(bit) for bit in paths[best]), costs[best]


def crc16_xmodem(data: bytes) -> int:
    """Return the XMODEM CRC-16 of ``data``."""
    return binascii.crc_hqx(data, 0)
