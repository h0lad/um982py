"""End-to-end OSNMA chain over an official stream capture."""

from pathlib import Path

import pytest

from um982py.experimental.inav_pages import (
    assemble_inav_word,
    assemble_osnma_subframe,
    decode_inav_page_part,
    parse_nma_header,
    read_inav_stream_csv,
)
from um982py.experimental.osnma import (
    collect_dsm,
    gst_subframe,
    parse_dsm_kroot,
    parse_mack_message,
    verify_chain_key,
    verify_dsm_kroot_padding,
    verify_dsm_kroot_signature,
    verify_tag,
    word_authenticated_data,
)

FIXTURE = Path(__file__).parent / "fixtures" / "inav-stream-six-satellites.csv"
"""Stream capture of two satellites of the official configuration one."""

SUBFRAME_PARTS = 30
ODD_PARTS = tuple(range(1, SUBFRAME_PARTS, 2))
SUBFRAMES = 8

_NMA_STATUS_VALUE = {
    "reserved": 0,
    "test": 1,
    "operational": 2,
    "do_not_use": 3,
}


@pytest.fixture(scope="module")
def streams() -> dict[int, tuple[bytes, ...]]:
    return read_inav_stream_csv(FIXTURE)


def _subframe(parts: tuple[bytes, ...], index: int) -> tuple[bytes, bytes]:
    """Return the HKROOT and MACK messages of one sub-frame."""
    start = index * SUBFRAME_PARTS
    osnma = b""
    for odd_index in ODD_PARTS:
        part = decode_inav_page_part(parts[start + odd_index])
        assert part.osnma is not None
        osnma += part.osnma
    subframe = assemble_osnma_subframe(osnma)
    return subframe.hkroot, subframe.mack


def _words(parts: tuple[bytes, ...], index: int) -> dict[int, object]:
    start = index * SUBFRAME_PARTS
    words = {}
    for part_index in range(0, SUBFRAME_PARTS, 2):
        word = assemble_inav_word(
            parts[start + part_index], parts[start + part_index + 1]
        )
        if word is not None:
            words[word.word_type] = word
    return words


def _subframe_time(words: dict[int, object]) -> tuple[int, int]:
    """Return week number and sub-frame start time of one sub-frame."""
    timing = words[5].timing  # type: ignore[attr-defined]
    assert timing is not None
    return timing.week_number, timing.time_of_week - 25


def _chain(streams: dict[int, tuple[bytes, ...]]) -> object:
    subframes = []
    headers = []
    for parts in streams.values():
        for index in range(SUBFRAMES):
            hkroot, _mack = _subframe(parts, index)
            subframes.append(hkroot)
            headers.append(parse_nma_header(hkroot[:1]))
    messages = collect_dsm(subframes, headers)
    kroot = next(
        message
        for (dsm_id, _owner), message in messages.items()
        if dsm_id <= 11
    )
    return parse_dsm_kroot(kroot, headers[0])


def test_stream_fixture_reads_both_satellites(
    streams: dict[int, tuple[bytes, ...]],
) -> None:
    assert 2 in streams and len(streams) >= 4
    for parts in streams.values():
        assert len(parts) >= SUBFRAMES * SUBFRAME_PARTS


def test_page_checksums_hold_for_every_page(
    streams: dict[int, tuple[bytes, ...]],
) -> None:
    checked = 0
    for parts in streams.values():
        for index in range(0, len(parts) - 1, 2):
            word = assemble_inav_word(parts[index], parts[index + 1])
            assert word is not None, index
            checked += 1
    assert checked >= 360


def test_dsm_kroot_assembles_and_its_signature_verifies(
    streams: dict[int, tuple[bytes, ...]],
) -> None:
    dsm = _chain(streams)
    assert dsm.tag_bits == 40 and dsm.key_bits == 128
    assert verify_dsm_kroot_padding(dsm)
    assert verify_dsm_kroot_signature(dsm, _public_key(dsm))


PUBLIC_KEY_1_HEX = (
    "0374A925CFA0FF1805E5C5A58FDBA31BF0145D5B5BE2F062D3F8BB2EE98F0F6DB0"
)
"""Compressed public key one of the configuration one test vector."""


def _public_key(dsm: object) -> bytes:
    """Return the public key applicable to the parsed message."""
    del dsm
    return bytes.fromhex(PUBLIC_KEY_1_HEX)


def test_disclosed_keys_verify_against_the_root(
    streams: dict[int, tuple[bytes, ...]],
) -> None:
    dsm = _chain(streams)
    gst0 = dsm.gst_start
    verified = 0
    for index in range(1, 5):
        _, mack = _subframe(streams[2], index)
        message = parse_mack_message(mack, dsm.key_bits, dsm.tag_bits)
        words = _words(streams[2], index)
        _week, subframe_start = _subframe_time(words)
        key_index = (subframe_start - (gst0 & 0xFFFFF)) // 30 + 1
        if key_index < 1:
            continue
        assert verify_chain_key(
            message.key, key_index, dsm.kroot, gst0, dsm.alpha
        )
        verified += 1
    assert verified >= 2


def test_tag0_of_a_sub_frame_verifies_with_the_disclosed_key(
    streams: dict[int, tuple[bytes, ...]],
) -> None:
    dsm = _chain(streams)
    parts = streams[2]
    tag_index = 4
    key_index = 5
    _, mack_tag = _subframe(parts, tag_index)
    _, mack_key = _subframe(parts, key_index)
    tag_message = parse_mack_message(mack_tag, dsm.key_bits, dsm.tag_bits)
    key_message = parse_mack_message(mack_key, dsm.key_bits, dsm.tag_bits)

    previous = _words(parts, tag_index - 1)
    navdata = word_authenticated_data(previous, 0)
    assert navdata is not None

    words = _words(parts, tag_index)
    week, subframe_start = _subframe_time(words)
    key_position = (subframe_start - (dsm.gst_start & 0xFFFFF)) // 30 + 2
    assert verify_chain_key(
        key_message.key, key_position, dsm.kroot, dsm.gst_start, dsm.alpha
    )

    header = parse_nma_header(_subframe(parts, tag_index)[0][:1])
    assert verify_tag(
        tag_message.tag0,
        key=key_message.key,
        prn_transmitting=2,
        subframe=gst_subframe(week, subframe_start),
        counter=1,
        nma_status=_NMA_STATUS_VALUE[header.status.value],
        navdata=navdata,
    )
