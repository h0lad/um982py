"""Galileo OSNMA verification: HKROOT, DSM-KROOT, TESLA and tag checks."""

import hashlib
import hmac
import xml.etree.ElementTree
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

from um982py.experimental.ecdsa_p256 import verify_ecdsa_p256
from um982py.experimental.inav_coding import bits_of, pack_bits
from um982py.experimental.inav_pages import (
    InavWord,
    NmaHeader,
    NmaStatus,
    OsnmaSubframe,
    PublicKeyStatus,
    assemble_inav_word,
    assemble_osnma_subframe,
    decode_inav_page_part,
)
from um982py.gnss import WEEK_SECONDS

__all__ = [
    "DsmHeader",
    "DsmKroot",
    "MacFunction",
    "MackMessage",
    "MackTag",
    "OsnmaReplay",
    "TagInfo",
    "VerifiedTag0",
    "collect_dsm",
    "dsm_kroot_signed_message",
    "gst_subframe",
    "gst_subframe_bits",
    "load_public_key",
    "mac_lookup_sequences",
    "parse_dsm_header",
    "parse_dsm_kroot",
    "parse_mack_message",
    "tag_key_offset",
    "tesla_chain_key",
    "verify_chain_key",
    "verify_dsm_kroot_padding",
    "verify_dsm_kroot_signature",
    "verify_macseq",
    "verify_osnma_stream",
    "verify_tag",
    "word_authenticated_data",
]

MACLT_SEQUENCES: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] = {
    27: (
        ("00S", "00E", "00E", "00E", "12S", "00E"),
        ("00S", "00E", "00E", "04S", "12S", "00E"),
    ),
    28: (
        ("00S", "00E", "00E", "00E", "00S", "00E", "00E", "12S", "00E", "00E"),
        ("00S", "00E", "00E", "00S", "00E", "00E", "04S", "12S", "00E", "00E"),
    ),
    31: (
        ("00S", "00E", "00E", "12S", "00E"),
        ("00S", "00E", "00E", "12S", "04S"),
    ),
    33: (
        ("00S", "00E", "04S", "00E", "12S", "00E"),
        ("00S", "00E", "00E", "12S", "00E", "12E"),
    ),
    34: (
        ("00S", "FLX", "04S", "FLX", "12S", "00E"),
        ("00S", "FLX", "00E", "12S", "00E", "12E"),
    ),
    35: (
        ("00S", "FLX", "04S", "FLX", "12S", "FLX"),
        ("00S", "FLX", "FLX", "12S", "FLX", "FLX"),
    ),
    36: (
        ("00S", "FLX", "04S", "FLX", "12S"),
        ("00S", "FLX", "00E", "12S", "12E"),
    ),
    37: (
        ("00S", "00E", "04S", "00E", "12S"),
        ("00S", "00E", "00E", "12S", "12E"),
    ),
    38: (
        ("00S", "FLX", "04S", "FLX", "12S"),
        ("00S", "FLX", "FLX", "12S", "FLX"),
    ),
    39: (
        ("00S", "FLX", "04S", "FLX"),
        ("00S", "FLX", "00E", "12S"),
    ),
    40: (
        ("00S", "00E", "04S", "12S"),
        ("00S", "00E", "00E", "12E"),
    ),
    41: (
        ("00S", "FLX", "04S", "FLX"),
        ("00S", "FLX", "FLX", "12S"),
    ),
}
"""MAC look-up table of the OSNMA SIS ICD: two alternating tag slots."""

KEY_SIZES = {0: 96, 1: 104, 2: 112, 3: 120, 4: 128, 5: 160, 6: 192, 7: 224, 8: 256}
"""Key lengths in bits indexed by the KS field."""

TAG_SIZES = {5: 20, 6: 24, 7: 28, 8: 32, 9: 40}
"""Tag lengths in bits indexed by the TS field."""

KROOT_BLOCKS = {0: None, 1: 7, 2: 8, 3: 9, 4: 10, 5: 11, 6: 12, 7: 13, 8: 14}
"""Number of DSM-KROOT blocks indexed by the NB field."""

PKR_BLOCKS = {7: 13, 8: 14, 9: 15, 10: 16}
SUBFRAME_SECONDS = 30

DSM_KROOT_FIXED_BITS = 104
"""Bits of the fixed field block of a DSM-KROOT message."""

AUTHENTICATED_WORD_BITS = {
    1: (6, 126),
    2: (6, 126),
    3: (6, 128),
    4: (6, 126),
    5: (6, 73),
    6: (6, 105),
    10: (86, 128),
}
"""Word-relative bit ranges of the authenticated data, MSB-first."""


class MacFunction(StrEnum):
    """The message authentication function of a chain."""

    HMAC_SHA256 = "hmac_sha256"


def mac_lookup_sequences(entry: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the two alternating tag slot sequences of a look-up entry."""
    sequences = MACLT_SEQUENCES.get(entry)
    if sequences is None:
        raise ValueError(f"The MAC look-up entry {entry} is not defined")
    return sequences


def gst_subframe(week_number: int, time_of_week: int) -> int:
    """Return the packed 32-bit sub-frame time of one GST instant.

    The value is the week number in the twelve most significant bits and
    the time of week in the twenty least significant bits, the
    representation used by the authentication messages.
    """
    return week_number << 20 | time_of_week


def gst_subframe_bits(week_number: int, time_of_week: int) -> bytes:
    """Return the packed 32-bit sub-frame time as bytes."""
    return gst_subframe(week_number, time_of_week).to_bytes(4, "big")


def _pack_gst_seconds(seconds: int) -> int:
    week, tow = divmod(seconds, WEEK_SECONDS)
    return gst_subframe(week % 4096, tow)


def _truncate(length: int, data: bytes) -> bytes:
    value = int.from_bytes(data, "big")
    kept = value >> (len(data) * 8 - length)
    return kept.to_bytes((length + 7) // 8, "big")


@dataclass(frozen=True, slots=True)
class DsmHeader:
    """Header of one digital signature message block."""

    dsm_id: int
    """Four-bit message identifier."""

    block_id: int
    """Four-bit block index within the message."""


def parse_dsm_header(hkroot_portion: bytes) -> DsmHeader:
    """Parse the eight-bit DSM header of a sub-frame's HKROOT section."""
    if len(hkroot_portion) != 1:
        raise ValueError("The DSM header is one byte")
    value = hkroot_portion[0]
    return DsmHeader(dsm_id=value >> 4, block_id=value & 0xF)


@dataclass(frozen=True, slots=True)
class DsmKroot:
    """One parsed DSM-KROOT message of the HKROOT stream."""

    nma_header: NmaHeader
    """Authentication header of the sub-frame that opened the message."""

    nb_dk: int
    """Field selecting the number of message blocks."""

    public_key_id: int
    """Identifier of the public key that signs the message."""

    chain_id: int
    """Chain that the root key belongs to."""

    hash_function: int
    """Chain hash function field."""

    mac_function: int
    """Chain MAC function field."""

    key_size: int
    """Key length field."""

    tag_size: int
    """Tag length field."""

    mac_lookup: int
    """MAC look-up table entry of the chain."""

    week_number: int
    """Week number of the root key time."""

    hours_of_week: int
    """Hours of week of the root key time."""

    alpha: bytes
    """Forty-eight-bit chain hash pattern."""

    kroot: bytes
    """Root key of the chain."""

    signature: bytes
    """Digital signature over the signed message."""

    padding: bytes
    """Padding bits of the message."""

    @property
    def key_bits(self) -> int:
        return KEY_SIZES[self.key_size]

    @property
    def tag_bits(self) -> int:
        return TAG_SIZES[self.tag_size]

    @property
    def gst_start(self) -> int:
        """Packed sub-frame time at which the chain enters into force."""
        return gst_subframe(self.week_number, self.hours_of_week * 3600)

    @property
    def blocks(self) -> int | None:
        """Number of message blocks, ``None`` for a reserved field."""
        return KROOT_BLOCKS[self.nb_dk]

    def manifest(self) -> dict[str, object]:
        return {
            "nb_dk": self.nb_dk,
            "public_key_id": self.public_key_id,
            "chain_id": self.chain_id,
            "hash_function": self.hash_function,
            "mac_function": self.mac_function,
            "key_size": self.key_bits,
            "tag_size": self.tag_bits,
            "mac_lookup": self.mac_lookup,
            "week_number": self.week_number,
            "hours_of_week": self.hours_of_week,
            "alpha": self.alpha.hex(),
            "kroot": self.kroot.hex(),
            "signature": self.signature.hex(),
            "padding": self.padding.hex(),
            "nma_header": {
                "status": self.nma_header.status.value,
                "chain_id": self.nma_header.chain_id,
                "public_key_status": self.nma_header.public_key_status.value,
            },
        }


def _dsm_payload(dsm_id: int, blocks: Mapping[int, bytes]) -> bytes | None:
    first = blocks.get(0)
    if first is None:
        return None
    sizes = KROOT_BLOCKS if dsm_id < 12 else PKR_BLOCKS
    count = sizes.get(first[0] >> 4)
    if count is None or any(index not in blocks for index in range(count)):
        return None
    return b"".join(blocks[index] for index in range(count))


def collect_dsm(
    subframes: Sequence[bytes], nma_headers: Sequence[NmaHeader]
) -> dict[tuple[int, int], bytes]:
    """Assemble complete DSM messages from the HKROOT sections of sub-frames.

    ``subframes`` holds the 15-byte HKROOT message of consecutive
    sub-frames and ``nma_headers`` their authentication headers. The first
    byte of each HKROOT message is the header portion, and the remaining
    bytes
    are DSM blocks addressed by their header. Pass one transmission of
    each DSM identifier. The second element of each returned key is zero
    for compatibility.
    """
    blocks: dict[int, dict[int, bytes]] = {}
    for subframe, _header in zip(subframes, nma_headers, strict=True):
        if len(subframe) != 15:
            raise ValueError("An HKROOT message is 15 bytes")
        dsm_header = parse_dsm_header(subframe[1:2])
        block = subframe[2:]
        blocks.setdefault(dsm_header.dsm_id, {})[dsm_header.block_id] = block
    messages: dict[tuple[int, int], bytes] = {}
    for dsm_id, message_blocks in blocks.items():
        if (payload := _dsm_payload(dsm_id, message_blocks)) is not None:
            messages[(dsm_id, 0)] = payload
    return messages


def parse_dsm_kroot(message: bytes, nma_header: NmaHeader) -> DsmKroot:
    """``message`` is the assembled DSM field of the required blocks, starting
    with the fixed field block. The public key identifier selects the key
    that signs the message, and the root key time is given as week number
    and hours of week.
    """
    bits = bits_of(message)
    fields = bits[:DSM_KROOT_FIXED_BITS]
    nb_dk = int(fields[0:4], 2)
    public_key_id = int(fields[4:8], 2)
    chain_id = int(fields[8:10], 2)
    hash_function = int(fields[12:14], 2)
    mac_function = int(fields[14:16], 2)
    key_size = int(fields[16:20], 2)
    tag_size = int(fields[20:24], 2)
    mac_lookup = int(fields[24:32], 2)
    week_number = int(fields[36:48], 2)
    hours_of_week = int(fields[48:56], 2)
    alpha = pack_bits(fields[56:104])
    if key_size not in KEY_SIZES or tag_size not in TAG_SIZES:
        raise ValueError("The message announces an unsupported key or tag size")
    key_bits = KEY_SIZES[key_size]
    kroot_start = DSM_KROOT_FIXED_BITS
    kroot = pack_bits(bits[kroot_start : kroot_start + key_bits])
    signature = pack_bits(bits[kroot_start + key_bits : kroot_start + key_bits + 512])
    padding = pack_bits(bits[kroot_start + key_bits + 512 :])
    return DsmKroot(
        nma_header=nma_header,
        nb_dk=nb_dk,
        public_key_id=public_key_id,
        chain_id=chain_id,
        hash_function=hash_function,
        mac_function=mac_function,
        key_size=key_size,
        tag_size=tag_size,
        mac_lookup=mac_lookup,
        week_number=week_number,
        hours_of_week=hours_of_week,
        alpha=alpha,
        kroot=kroot,
        signature=signature,
        padding=padding,
    )


def dsm_kroot_signed_message(dsm: DsmKroot) -> bytes:
    """The message concatenates the authentication header, the chain
    parameters and the root key, right-padded to whole bytes.
    """
    bits = bits_of(_nma_header_bytes(dsm.nma_header))
    bits += f"{dsm.chain_id:02b}"
    bits += "01"
    bits += f"{dsm.hash_function:02b}"
    bits += f"{dsm.mac_function:02b}"
    bits += f"{dsm.key_size:04b}"
    bits += f"{dsm.tag_size:04b}"
    bits += f"{dsm.mac_lookup:08b}"
    bits += "0000"
    bits += f"{dsm.week_number:012b}"
    bits += f"{dsm.hours_of_week:08b}"
    bits += bits_of(dsm.alpha)
    bits += bits_of(dsm.kroot)
    return pack_bits(bits)


def _nma_header_bytes(header: NmaHeader) -> bytes:
    status = {"reserved": 0, "test": 1, "operational": 2, "do_not_use": 3}
    public_key_status = {
        "reserved": 0,
        "nominal": 1,
        "end_of_chain": 2,
        "chain_revoked": 3,
        "new_public_key": 4,
        "public_key_revoked": 5,
        "new_merkle_tree": 6,
        "alert_message": 7,
    }
    value = (
        status[header.status.value] << 6
        | header.chain_id << 4
        | public_key_status[header.public_key_status.value] << 1
        | header.reserved
    )
    return value.to_bytes(1, "big")


def verify_dsm_kroot_padding(dsm: DsmKroot) -> bool:
    if not dsm.padding:
        return True
    digest = hashlib.sha256(dsm_kroot_signed_message(dsm) + dsm.signature).digest()
    return _truncate(len(dsm.padding) * 8, digest) == dsm.padding


def verify_dsm_kroot_signature(dsm: DsmKroot, public_key: bytes) -> bool:
    return verify_ecdsa_p256(dsm_kroot_signed_message(dsm), dsm.signature, public_key)


def tesla_chain_key(
    next_key: bytes, subframe: int, alpha: bytes, key_bits: int
) -> bytes:
    """Derive the chain key that precedes ``next_key``.

    ``subframe`` is the packed sub-frame time at which the derived key was
    transmitted. The function is the chain step of the OSNMA SIS ICD: the
    hash of the next key, the sub-frame time and the chain pattern,
    truncated to the chain key length.
    """
    digest = hashlib.sha256(next_key + subframe.to_bytes(4, "big") + alpha).digest()
    return _truncate(key_bits, digest)


def verify_chain_key(
    key: bytes, key_index: int, kroot: bytes, gst_start: int, alpha: bytes
) -> bool:
    """Verify a chain key against the root key by recursive derivation.

    ``key`` is the disclosed key of index ``key_index`` counted from the
    root, ``gst_start`` the packed time at which the chain enters into
    force. The root key applies to the sub-frame thirty seconds before
    that time.
    """
    key_bits = len(key) * 8
    current = key
    if key_index < 0 or len(key) != len(kroot) or not key:
        return False
    week, tow = gst_start >> 20, gst_start & 0xFFFFF
    seconds = week * WEEK_SECONDS + tow + (key_index - 2) * SUBFRAME_SECONDS
    for _ in range(key_index):
        current = tesla_chain_key(current, _pack_gst_seconds(seconds), alpha, key_bits)
        seconds -= SUBFRAME_SECONDS
    return hmac.compare_digest(current, kroot)


def tag_key_offset(adkd: int) -> int:
    """Tags are verified with the key disclosed one MACK message later, and
    the slow authentication type adds ten further sub-frames of delay.
    """
    if adkd == 12:
        return 11
    if adkd in (0, 4):
        return 1
    raise ValueError(f"The data type {adkd} has no key offset")


@dataclass(frozen=True, slots=True)
class TagInfo:
    """Tag information of one MACK tag slot."""

    prn_d: int
    """Satellite that transmitted the authenticated data."""

    adkd: int
    """Authenticated data type."""

    flags: int
    """Remaining four bits of the information field."""


@dataclass(frozen=True, slots=True)
class MackTag:
    """One tag of a MACK message."""

    counter: int
    """Position of the tag within the message, starting at one."""

    tag: bytes
    """Truncated MAC value, right-padded to whole bytes."""

    info: TagInfo
    """Tag information of the slot."""


@dataclass(frozen=True, slots=True)
class MackMessage:
    """One parsed MACK message of 480 bits."""

    tag0: bytes
    """First tag of the message, authenticating the transmitting satellite."""

    macseq: int
    """Twelve-bit sequence authenticating the flexible tag information."""

    cut_off: int
    """Four-bit data cut-off point of the first tag."""

    tags: tuple[MackTag, ...]
    """Remaining tags with their information fields."""

    key: bytes
    """Disclosed chain key of the message."""

    def manifest(self) -> dict[str, object]:
        return {
            "tag0": self.tag0.hex(),
            "macseq": self.macseq,
            "cut_off": self.cut_off,
            "tags": [
                {
                    "counter": tag.counter,
                    "tag": tag.tag.hex(),
                    "prn_d": tag.info.prn_d,
                    "adkd": tag.info.adkd,
                    "flags": tag.info.flags,
                }
                for tag in self.tags
            ],
            "key": self.key.hex(),
        }


def _mack_tag_count(key_bits: int, tag_bits: int) -> int:
    return (480 - key_bits) // (tag_bits + 16)


def parse_mack_message(mack: bytes, key_bits: int, tag_bits: int) -> MackMessage:
    """``key_bits`` and ``tag_bits`` are the chain parameters announced by the
    DSM-KROOT in force. The message opens with the first tag, the sequence
    field and the cut-off point, continues with the remaining tags and
    their information fields and closes with the disclosed chain key.
    """
    bits = bits_of(mack)
    if len(bits) < 480:
        raise ValueError("A MACK message is 480 bits")
    tag_count = _mack_tag_count(key_bits, tag_bits)
    if tag_count < 2:
        raise ValueError("The chain parameters leave no room for tags")
    tag0 = pack_bits(bits[:tag_bits])
    macseq = int(bits[tag_bits : tag_bits + 12], 2)
    cut_off = int(bits[tag_bits + 12 : tag_bits + 16], 2)
    tags = []
    offset = tag_bits + 16
    for counter in range(2, tag_count + 1):
        tag_bits_value = bits[offset : offset + tag_bits]
        info_bits = bits[offset + tag_bits : offset + tag_bits + 16]
        tags.append(
            MackTag(
                counter=counter,
                tag=pack_bits(tag_bits_value),
                info=TagInfo(
                    prn_d=int(info_bits[:8], 2),
                    adkd=int(info_bits[8:12], 2),
                    flags=int(info_bits[12:16], 2),
                ),
            )
        )
        offset += tag_bits + 16
    key = pack_bits(bits[offset : offset + key_bits])
    return MackMessage(
        tag0=tag0,
        macseq=macseq,
        cut_off=cut_off,
        tags=tuple(tags),
        key=key,
    )


def _mac(key: bytes, message: bytes, function: int) -> bytes:
    if function != 0:
        raise ValueError("Only the HMAC-SHA-256 chain MAC function is supported")
    return hmac.new(key, message, hashlib.sha256).digest()


def word_authenticated_data(words: Mapping[int, InavWord], adkd: int) -> str | None:
    """For the ephemeris, clock and status type the words one to five of one
    sub-frame contribute their authenticated ranges, while the timing type
    uses words six and ten. The returned MSB-first bit string is exact and
    is not padded to whole bytes. ``None`` is returned when a required word
    is missing.
    """
    required: tuple[int, ...]
    if adkd in (0, 12):
        required = (1, 2, 3, 4, 5)
    elif adkd == 4:
        required = (6, 10)
    else:
        raise ValueError(f"The data type {adkd} has no authenticated data")
    bits = ""
    for word_type in required:
        word = words.get(word_type)
        if word is None or word.word_type != word_type:
            return None
        start, end = AUTHENTICATED_WORD_BITS[word_type]
        bits += word.bits[start:end]
    return bits


def verify_tag(
    tag: bytes,
    *,
    key: bytes,
    prn_transmitting: int,
    subframe: int,
    counter: int,
    nma_status: int,
    navdata: str,
    function: int = 0,
    prn_data: int | None = None,
    tag_bits: int | None = None,
) -> bool:
    """``subframe`` is the packed time of the sub-frame carrying the tag,
    ``nma_status`` the two-bit status of its authentication header and
    ``navdata`` the exact authenticated data bits of the previous
    sub-frame, as returned by :func:`word_authenticated_data`. The
    optional ``prn_data`` identifies the satellite that transmitted the
    authenticated data and is omitted for the first tag, which
    authenticates the transmitting satellite itself. Pass ``tag_bits``
    for a non-byte-aligned tag, encoded with zero padding on the right.
    """
    if tag_bits is None:
        tag_bits = len(tag) * 8
    if not 0 < tag_bits <= 256 or len(tag) != (tag_bits + 7) // 8:
        return False
    bits = f"{prn_transmitting:08b}"
    if prn_data is not None:
        bits = f"{prn_data:08b}" + bits
    bits += f"{subframe:032b}"
    bits += f"{counter:08b}"
    bits += f"{nma_status:02b}"
    bits += navdata
    mac = _mac(key, pack_bits(bits), function)
    return hmac.compare_digest(pack_bits(bits_of(mac)[:tag_bits]), tag)


def verify_macseq(
    macseq: int,
    *,
    key: bytes,
    prn_transmitting: int,
    subframe: int,
    flexible_infos: Sequence[TagInfo],
    function: int = 0,
) -> bool:
    """Verify the sequence field of a MACK message.

    ``flexible_infos`` are the information fields of the tags whose data
    type is flexible in the look-up sequence of the chain, in message
    order.
    """
    bits = f"{prn_transmitting:08b}"
    bits += f"{subframe:032b}"
    for info in flexible_infos:
        bits += f"{info.prn_d:08b}"
        bits += f"{info.adkd:04b}"
        bits += f"{info.flags:04b}"
    mac = _mac(key, pack_bits(bits), function)
    return _truncate(12, mac) == macseq.to_bytes(2, "big")


def load_public_key(path: Path) -> tuple[int, str, bytes]:
    """Returns the key identifier, the stated algorithm and the compressed
    point. Certificate chain verification is out of scope of this loader.
    """
    root = xml.etree.ElementTree.parse(path).getroot()  # noqa: S314
    body = root.find("body")
    if body is None:
        raise ValueError("The key record has no body element")
    record = body.find("PublicKey")
    if record is None:
        raise ValueError("The key record has no PublicKey element")
    pkid = int(record.findtext("PKID", default="-1"))
    algorithm = record.findtext("PKType", default="")
    point = bytes.fromhex(record.findtext("point", default=""))
    return pkid, algorithm, point


@dataclass(frozen=True, slots=True)
class VerifiedTag0:
    """One matching ADKD 0 tag and the GST of the data it covers."""

    svid: int
    tag_gst: int
    """Packed GST of the sub-frame containing the tag."""

    data_gst: int
    """Packed GST of the sub-frame containing the matching navigation data."""

    status: NmaStatus
    tag: bytes
    tag_bits: int


@dataclass(frozen=True, slots=True)
class OsnmaReplay:
    """Results of offline signature, chain key and Tag0 checks."""

    osnma_subframes: int
    """Count of complete, nonzero OSNMA sub-frames across all satellites."""

    roots: tuple[DsmKroot, ...]
    verified_tags: tuple[VerifiedTag0, ...]


@dataclass(frozen=True, slots=True)
class _ReplaySubframe:
    words: dict[int, InavWord]
    osnma: OsnmaSubframe | None


def _replay_subframes(parts: Sequence[bytes]) -> dict[int, _ReplaySubframe]:
    # The E1 even parts start at GST_SF + 1, +3, ... +29. WT5
    # reports the GST of its even part and anchors the page positions.
    paired = [assemble_inav_word(even, odd) for even, odd in pairwise(parts)]
    frames: dict[int, _ReplaySubframe] = {}
    ambiguous: set[int] = set()
    for index, word in enumerate(paired):
        if word is None or word.timing is None:
            continue
        tow = word.timing.time_of_week
        phase = tow % SUBFRAME_SECONDS
        if tow >= WEEK_SECONDS or phase % 2 != 1:
            continue
        start = index - phase + 1
        end = start + SUBFRAME_SECONDS
        if start < 0 or end > len(parts):
            continue
        seconds = word.timing.gst_seconds - phase
        page_words = paired[start:end:2]
        words = {entry.word_type: entry for entry in page_words if entry is not None}
        fields = b""
        if None not in page_words:
            fields = b"".join(
                decode_inav_page_part(part).osnma or b""
                for part in parts[start + 1 : end : 2]
            )
        frame = _ReplaySubframe(
            words=words,
            osnma=assemble_osnma_subframe(fields) if any(fields) else None,
        )
        if seconds in frames and frames[seconds] != frame:
            ambiguous.add(seconds)
        frames[seconds] = frame
    return {
        seconds: frame for seconds, frame in frames.items() if seconds not in ambiguous
    }


def _replay_roots(
    subframes: Sequence[OsnmaSubframe], public_keys: Mapping[int, bytes]
) -> tuple[DsmKroot, ...]:
    groups: dict[tuple[int, int], dict[int, bytes]] = {}
    checked: set[tuple[int, bytes]] = set()
    roots: list[DsmKroot] = []
    for subframe in subframes:
        header_byte = subframe.hkroot[0]
        dsm = parse_dsm_header(subframe.hkroot[1:2])
        if dsm.dsm_id >= 12:
            continue
        blocks = groups.setdefault((header_byte, dsm.dsm_id), {})
        blocks[dsm.block_id] = subframe.hkroot[2:]
        payload = _dsm_payload(dsm.dsm_id, blocks)
        if payload is None or (header_byte, payload) in checked:
            continue
        checked.add((header_byte, payload))
        public_key = public_keys.get(payload[0] & 0xF)
        if public_key is None:
            continue
        try:
            root = parse_dsm_kroot(payload, subframe.header)
        except ValueError:
            continue
        signed = dsm_kroot_signed_message(root)
        if (
            len(root.signature) == 64
            and len(root.padding) < 13
            and signed[1:] == payload[1 : len(signed)]
            and root.hours_of_week < 168
            and verify_dsm_kroot_padding(root)
            and verify_dsm_kroot_signature(root, public_key)
        ):
            roots.append(root)
    return tuple(sorted(roots, key=lambda root: root.gst_start))


def _nominal_header(header: NmaHeader, chain_id: int) -> bool:
    return (
        header.chain_id == chain_id
        and header.status in (NmaStatus.TEST, NmaStatus.OPERATIONAL)
        and header.public_key_status == PublicKeyStatus.NOMINAL
    )


def verify_osnma_stream(
    streams: Mapping[int, Sequence[bytes]], public_keys: Mapping[int, bytes]
) -> OsnmaReplay:
    """Replay consecutive Galileo E1-B page parts keyed by decimal SVID.

    Supply trusted P-256 public points keyed by OSNMA public key ID. Input
    parts occupy consecutive one-second slots. Use empty bytes for missing
    parts to preserve their positions. GST is taken from checksum-verified
    WT5 in each sub-frame.

    This checks self-authenticating ADKD 0 tags on nominal SHA-256 /
    HMAC-SHA-256 chains using the same satellite's key in the next
    sub-frame. Results are historical cryptographic matches. Capture-time
    freshness, service transitions and tag accumulation are outside this
    offline check.
    """
    frames = {
        (seconds, svid): frame
        for svid, parts in streams.items()
        if 1 <= svid <= 36
        for seconds, frame in _replay_subframes(parts).items()
    }
    ordered = sorted(frames.items())
    subframes = [frame.osnma for _, frame in ordered if frame.osnma is not None]
    roots = _replay_roots(subframes, public_keys)
    matches: list[VerifiedTag0] = []
    verified_keys: dict[DsmKroot, tuple[int, bytes]] = {}
    for (seconds, svid), frame in ordered:
        following = frames.get((seconds + SUBFRAME_SECONDS, svid))
        previous = frames.get((seconds - SUBFRAME_SECONDS, svid))
        if (
            frame.osnma is None
            or following is None
            or following.osnma is None
            or previous is None
        ):
            continue
        tag_gst = _pack_gst_seconds(seconds)
        key_gst = _pack_gst_seconds(seconds + SUBFRAME_SECONDS)
        applicable = [root for root in roots if root.gst_start <= key_gst]
        if not applicable:
            continue
        root = applicable[-1]
        if (
            root.gst_start > tag_gst
            or root.hash_function != 0
            or root.mac_function != 0
            or root.mac_lookup not in MACLT_SEQUENCES
            or not _nominal_header(root.nma_header, root.chain_id)
            or not _nominal_header(frame.osnma.header, root.chain_id)
            or not _nominal_header(following.osnma.header, root.chain_id)
        ):
            continue
        message = parse_mack_message(frame.osnma.mack, root.key_bits, root.tag_bits)
        if message.cut_off == 0:
            continue
        navdata = word_authenticated_data(previous.words, 0)
        if navdata is None or previous.words[4].svid != svid:
            continue
        if len({previous.words[index].iod_nav for index in (1, 2, 3, 4)}) != 1:
            continue
        key = parse_mack_message(following.osnma.mack, root.key_bits, root.tag_bits).key
        start = root.week_number * WEEK_SECONDS + root.hours_of_week * 3600
        last_seconds, last_key = verified_keys.get(
            root, (start - SUBFRAME_SECONDS, root.kroot)
        )
        steps = (seconds + SUBFRAME_SECONDS - last_seconds) // SUBFRAME_SECONDS
        next_gst = _pack_gst_seconds(last_seconds + SUBFRAME_SECONDS)
        if not verify_chain_key(key, steps, last_key, next_gst, root.alpha):
            continue
        verified_keys[root] = (seconds + SUBFRAME_SECONDS, key)
        status = frame.osnma.header.status
        if verify_tag(
            message.tag0,
            key=key,
            prn_transmitting=svid,
            subframe=tag_gst,
            counter=1,
            nma_status=frame.osnma.hkroot[0] >> 6,
            navdata=navdata,
            tag_bits=root.tag_bits,
        ):
            matches.append(
                VerifiedTag0(
                    svid=svid,
                    tag_gst=tag_gst,
                    data_gst=_pack_gst_seconds(seconds - SUBFRAME_SECONDS),
                    status=status,
                    tag=message.tag0,
                    tag_bits=root.tag_bits,
                )
            )
    return OsnmaReplay(len(subframes), roots, tuple(matches))
