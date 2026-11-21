import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import osnma_example
from osnma_example import (
    ALPHA_HEX,
    AUTHENTICATED_DATA_4_HEX,
    CHAIN_KEYS,
    DSM_KROOT_HEX,
    GST_START,
    MACK_FIRST_HEX,
    MACK_SECOND_HEX,
    PUBLIC_KEY_HEX,
    SIGNED_MESSAGE_HEX,
)
from um982py.experimental.ecdsa_p256 import (
    InvalidSignature,
    decompress_public_key,
    verify_ecdsa_p256,
)
from um982py.experimental.inav_coding import bits_of
from um982py.experimental.inav_pages import NmaStatus, PublicKeyStatus
from um982py.experimental.osnma import (
    DsmKroot,
    TagInfo,
    dsm_kroot_signed_message,
    gst_subframe,
    mac_lookup_sequences,
    parse_dsm_header,
    parse_dsm_kroot,
    parse_mack_message,
    tag_key_offset,
    tesla_chain_key,
    verify_chain_key,
    verify_dsm_kroot_padding,
    verify_dsm_kroot_signature,
    verify_macseq,
    verify_tag,
    word_authenticated_data,
)


@pytest.fixture(scope="module")
def dsm(example_header: object) -> DsmKroot:
    return parse_dsm_kroot(
        bytes.fromhex(DSM_KROOT_HEX), example_header
    )


def test_dsm_header_splits_identifier_and_block() -> None:
    header = parse_dsm_header(b"\x21")
    assert header.dsm_id == 2 and header.block_id == 1


def test_dsm_kroot_fields_match_the_official_example(dsm: DsmKroot) -> None:
    assert dsm.nb_dk == 2 and dsm.blocks == 8
    assert dsm.public_key_id == 2
    assert dsm.chain_id == 0
    assert dsm.hash_function == 0 and dsm.mac_function == 0
    assert dsm.key_bits == 128 and dsm.tag_bits == 40
    assert dsm.mac_lookup == 34
    assert dsm.week_number == 1248 and dsm.hours_of_week == 96
    assert dsm.alpha.hex().upper() == ALPHA_HEX.upper()
    assert dsm.kroot.hex().upper() == CHAIN_KEYS[0].upper()


def test_signed_message_matches_the_official_example(dsm: DsmKroot) -> None:
    assert dsm_kroot_signed_message(dsm) == bytes.fromhex(SIGNED_MESSAGE_HEX)


def test_padding_verifies(dsm: DsmKroot) -> None:
    assert verify_dsm_kroot_padding(dsm)


def test_signature_verifies_with_the_official_key(dsm: DsmKroot) -> None:
    assert verify_dsm_kroot_signature(dsm, bytes.fromhex(PUBLIC_KEY_HEX))
    kroot_offset = DSM_KROOT_HEX.upper().find(dsm.kroot.hex().upper())
    tampered_hex = (
        DSM_KROOT_HEX[:kroot_offset]
        + f"{dsm.kroot[0] ^ 1:02x}"
        + DSM_KROOT_HEX[kroot_offset + 2 :]
    )
    tampered = parse_dsm_kroot(bytes.fromhex(tampered_hex), dsm.nma_header)
    assert not verify_dsm_kroot_signature(tampered, bytes.fromhex(PUBLIC_KEY_HEX))


def test_public_key_decompression() -> None:
    key = bytes.fromhex(PUBLIC_KEY_HEX)
    x, y = decompress_public_key(
        bytes([2 + (key[-1] & 1)]) + key[1:33]
    )
    assert (x, y) == (int.from_bytes(key[1:33], "big"), int.from_bytes(key[33:], "big"))


def test_signature_rejects_bad_lengths() -> None:
    with pytest.raises(InvalidSignature):
        verify_ecdsa_p256(b"x", bytes(63), bytes.fromhex(PUBLIC_KEY_HEX))


def test_example_header_fixture() -> None:
    assert osnma_example.example_header is not None


def test_chain_key_derivation_follows_the_official_example(dsm: DsmKroot) -> None:
    alpha = bytes.fromhex(ALPHA_HEX)
    k1 = tesla_chain_key(
        bytes.fromhex(CHAIN_KEYS[2]),
        gst_subframe(1248, 345600),
        alpha,
        128,
    )
    assert k1.hex().upper() == CHAIN_KEYS[1].upper()
    k0 = tesla_chain_key(k1, gst_subframe(1248, 345570), alpha, 128)
    assert k0.hex().upper() == CHAIN_KEYS[0].upper()


def test_chain_key_verification_against_the_root(dsm: DsmKroot) -> None:
    alpha = bytes.fromhex(ALPHA_HEX)
    gst_start = gst_subframe(*GST_START)
    for index in (1, 2, 3, 4):
        assert verify_chain_key(
            bytes.fromhex(CHAIN_KEYS[index]),
            index,
            dsm.kroot,
            gst_start,
            alpha,
        )


@pytest.mark.parametrize("week", [0, 1251])
def test_chain_key_verification_across_gst_week_boundary(week: int) -> None:
    disclosed = bytes.fromhex(CHAIN_KEYS[1])
    alpha = bytes.fromhex(ALPHA_HEX)
    root_time = gst_subframe((week - 1) % 4096, 604770)
    root = tesla_chain_key(disclosed, root_time, alpha, 128)
    assert verify_chain_key(disclosed, 1, root, gst_subframe(week, 0), alpha)


def test_mack_first_message_matches_the_official_table() -> None:
    mack = parse_mack_message(bytes.fromhex(MACK_FIRST_HEX), 128, 40)
    assert mack.tag0.hex().upper() == "4DA9D1D763"
    assert mack.macseq == 0xDE4
    assert mack.cut_off == 0xF
    assert mack.key.hex().upper() == CHAIN_KEYS[2].upper()
    table = {
        2: ("DE4439ED5A", 24, 0),
        3: ("765C4FFE3D", 27, 0),
        4: ("E7025D4D0A", 2, 12),
        5: ("4947DAFF18", 12, 0),
        6: ("97FF3ABD23", 18, 12),
    }
    for tag in mack.tags:
        expected_tag, prn_d, adkd = table[tag.counter]
        assert tag.tag.hex().upper() == expected_tag
        assert tag.info.prn_d == prn_d
        assert tag.info.adkd == adkd


def test_mack_second_message_carries_the_next_key() -> None:
    mack = parse_mack_message(bytes.fromhex(MACK_SECOND_HEX), 128, 40)
    assert mack.tag0.hex().upper() == "E37BC4F858"
    assert mack.macseq == 0xB08
    assert mack.key.hex().upper() == CHAIN_KEYS[3].upper()


@pytest.mark.parametrize(
    ("tag_hex", "tag_bits"), [("E37BC4F858", None), ("E37BC0", 20), ("E37BC4F0", 28)]
)
def test_tag0_verification_of_the_official_example(
    example_words: dict[int, object], tag_hex: str, tag_bits: int | None,
) -> None:
    navdata = word_authenticated_data(example_words, 0)
    assert navdata is not None
    assert verify_tag(
        bytes.fromhex(tag_hex),
        key=bytes.fromhex(CHAIN_KEYS[4]),
        prn_transmitting=2,
        subframe=gst_subframe(1248, 345660),
        counter=1,
        nma_status=2,
        navdata=navdata,
        tag_bits=tag_bits,
    )


def test_adkd4_tag_verification_of_the_official_example(
    example_words: dict[int, object],
) -> None:
    navdata = word_authenticated_data(example_words, 4)
    assert navdata is not None
    assert bits_of(bytes.fromhex(AUTHENTICATED_DATA_4_HEX))[:141] == navdata
    assert verify_tag(
        bytes.fromhex("7BB238C883"),
        key=bytes.fromhex(CHAIN_KEYS[4]),
        prn_transmitting=2,
        subframe=gst_subframe(1248, 345660),
        counter=3,
        nma_status=2,
        navdata=navdata,
        prn_data=2,
    )


def test_adkd12_tag_verification_of_the_official_example(
    example_words: dict[int, object],
) -> None:
    navdata = word_authenticated_data(example_words, 0)
    assert navdata is not None
    assert verify_tag(
        bytes.fromhex("91F230FE4D"),
        key=bytes.fromhex(CHAIN_KEYS[14]),
        prn_transmitting=2,
        subframe=gst_subframe(1248, 345660),
        counter=5,
        nma_status=2,
        navdata=navdata,
        prn_data=2,
    )


def test_macseq_verification_of_the_official_example() -> None:
    infos = (
        TagInfo(prn_d=0x12, adkd=0, flags=0x5),
        TagInfo(prn_d=0x05, adkd=0, flags=0xF),
    )
    assert verify_macseq(
        0xB08,
        key=bytes.fromhex(CHAIN_KEYS[4]),
        prn_transmitting=2,
        subframe=gst_subframe(1248, 345660),
        flexible_infos=infos,
    )


def test_key_offsets_follow_the_slow_mac_rule() -> None:
    assert tag_key_offset(0) == 1
    assert tag_key_offset(4) == 1
    assert tag_key_offset(12) == 11
    with pytest.raises(ValueError):
        tag_key_offset(7)


def test_mac_lookup_sequences_of_the_official_configuration() -> None:
    first, _second = mac_lookup_sequences(34)
    assert first[0] == "00S"
    assert "FLX" in first
    with pytest.raises(ValueError):
        mac_lookup_sequences(26)


def test_dsm_manifest_is_plain_data(dsm: DsmKroot) -> None:
    manifest = dsm.manifest()
    assert manifest["key_size"] == 128
    assert manifest["nma_header"]["status"] == NmaStatus.OPERATIONAL.value
    assert manifest["nma_header"]["public_key_status"] == (
        PublicKeyStatus.NOMINAL.value
    )
