import pytest

from osnma_example import AUTHENTICATED_DATA_HEX
from um982py.experimental.inav_coding import (
    INAV_SYNC_PATTERN,
    bits_of,
    convolutional_decode,
    convolutional_encode,
    inav_crc24,
    interleave,
    pack_bits,
)
from um982py.experimental.inav_pages import (
    SarField,
    SarService,
    assemble_inav_word,
    assemble_sar_long_rlm,
    assemble_sar_short_rlm,
    decode_sar_beacon_id,
    decode_sar_field,
    pair_inav_words,
)


def test_crc24_matches_all_pages_of_the_official_example(
    example_parts: tuple[bytes, ...],
) -> None:
    verified = 0
    for index in range(0, len(example_parts), 2):
        even = bits_of(example_parts[index])
        odd = bits_of(example_parts[index + 1])
        protected = even[:114] + odd[:82]
        assert inav_crc24(protected) == int(odd[82:106], 2)
        verified += 1
    assert verified == 15


def test_word_assembly_rejects_mismatched_pairs(
    example_parts: tuple[bytes, ...],
) -> None:
    word = assemble_inav_word(example_parts[0], example_parts[1])
    assert word is not None and word.word_type == 2
    mixed = assemble_inav_word(example_parts[0], example_parts[3])
    assert mixed is None


def test_pair_inav_words_recovers_all_words(
    example_parts: tuple[bytes, ...],
) -> None:
    words = pair_inav_words(example_parts[0::2], example_parts[1::2])
    assert {word.word_type for word in words} >= {0, 1, 2, 3, 4, 5}


def test_word_fields_of_the_official_example(
    example_words: dict[int, object],
) -> None:
    word_five = example_words[5]
    assert word_five.timing is not None  # type: ignore[attr-defined]
    assert word_five.timing.week_number == 1248  # type: ignore[attr-defined]
    assert word_five.timing.time_of_week == 345655  # type: ignore[attr-defined]
    word_four = example_words[4]
    assert word_four.svid == 2  # type: ignore[attr-defined]
    assert word_four.iod_nav == example_words[1].iod_nav  # type: ignore[attr-defined]


def test_authenticated_data_of_the_official_example(
    example_words: dict[int, object],
) -> None:
    from um982py.experimental.osnma import word_authenticated_data

    navdata = word_authenticated_data(example_words, 0)
    assert navdata is not None
    expected = bits_of(bytes.fromhex(AUTHENTICATED_DATA_HEX))[:549]
    assert navdata == expected


def test_sar_field_decodes_start_identifier_and_data() -> None:
    bits = "1" + "1" + "01001" + "0" * 15  # start, long, 20 data bits
    field = decode_sar_field(pack_bits(bits))
    assert isinstance(field, SarField)
    assert field.start
    assert field.long_rlm
    assert bits_of(field.data)[:20] == bits[2:22]
    assert field.data[-1] & 0xF == 0


def test_sar_spare_classification_uses_the_following_start_bit() -> None:
    alternating = decode_sar_field(pack_bits("10" * 11))
    next_start = decode_sar_field(pack_bits("1" + "0" * 21))
    continuation = decode_sar_field(bytes(3))
    assert alternating.is_spare_before(next_start)
    assert not alternating.is_spare_before(continuation)


@pytest.mark.parametrize(
    ("beacon", "country_code", "label"),
    [
        ("9A22BE29630F010", 209, "GAL-EU5"),
        ("9c02be29630f0a0", 224, "GAL-EU4"),
        ("9C62FFFFFFFFF03", 227, None),
    ],
)
def test_decode_sar_orbitography_label(
    beacon: str,
    country_code: int,
    label: str | None,
) -> None:
    assert decode_sar_beacon_id(beacon) == {
        "country_code": country_code,
        "protocol_family": "user",
        "protocol_code_bits": "000",
        "orbitography_label": label,
    }


def test_decode_sar_location_protocol_code() -> None:
    assert decode_sar_beacon_id("193BF6A028BFDFF") == {
        "country_code": 201,
        "protocol_family": "location",
        "protocol_code_bits": "1101",
    }


def _sar_parts(
    beacon: str, code: int, parameters: str, *, long_rlm: bool
) -> list[SarField]:
    payload = f"{int(beacon, 16):060b}{code:04b}{parameters}"
    payload += str(payload.count("1") % 2)
    return [
        SarField(
            start=index == 0,
            long_rlm=long_rlm,
            data=pack_bits(payload[index : index + 20]),
        )
        for index in range(0, len(payload), 20)
    ]


@pytest.mark.parametrize(
    ("code", "parameters", "service"),
    [
        (1, 0x4000, SarService.ACKNOWLEDGEMENT_TYPE_1),
        (1, 0x2000, SarService.SPARE),
        (5, 0x091A, SarService.SPARE),
        (15, 0x091A, SarService.TEST),
    ],
)
def test_sar_short_rlm_assembles_from_four_parts(
    code: int,
    parameters: int,
    service: SarService,
) -> None:
    beacon = "0C621A74630F1D0"
    parts = _sar_parts(beacon, code, f"{parameters:015b}", long_rlm=False)
    rlm = assemble_sar_short_rlm(parts)
    assert rlm is not None
    assert rlm.beacon_hex == beacon
    assert rlm.message_code == code
    assert int.from_bytes(rlm.parameters, "big") >> 1 == parameters
    assert rlm.service == service


def test_sar_short_rlm_rejects_inconsistent_identifier() -> None:
    parts = [
        SarField(start=index == 0, long_rlm=index == 0, data=bytes(3))
        for index in range(4)
    ]
    assert assemble_sar_short_rlm(parts) is None


def test_sar_long_rlm_assembles_from_eight_parts() -> None:
    beacon = "A0434CEB630F190"
    parameters = 0x5BCD_EF01_2345_6789_ABCD_EF01
    parts = _sar_parts(beacon, 3, f"{parameters:095b}", long_rlm=True)
    rlm = assemble_sar_long_rlm(parts)
    assert rlm is not None
    assert rlm.beacon_hex == beacon
    assert rlm.message_code == 3
    assert len(rlm.parameters) == 12
    assert int.from_bytes(rlm.parameters, "big") >> 1 == parameters
    assert rlm.service == SarService.SPARE
    last = parts[-1].data
    parts[-1] = SarField(
        start=False, long_rlm=True, data=last[:2] + bytes([last[2] ^ 0x10])
    )
    assert assemble_sar_long_rlm(parts) is None


def test_sar_long_rlm_requires_message_sequence() -> None:
    parts = [SarField(start=False, long_rlm=True, data=bytes(3))] * 8
    assert assemble_sar_long_rlm(parts) is None


def test_convolutional_round_trip_reproduces_the_part(
    example_parts: tuple[bytes, ...],
) -> None:
    for part in example_parts[:4]:
        info = bits_of(part)[:120]
        coded = convolutional_encode(info)
        assert len(coded) == 240
        decoded, errors = convolutional_decode(coded)
        assert decoded == info
        assert errors == 0


def test_interleave_is_inverted_by_deinterleave() -> None:
    from um982py.experimental.inav_coding import deinterleave

    stream = "".join(str(index % 7 % 2) for index in range(240))
    assert deinterleave(interleave(stream)) == stream
    assert interleave(deinterleave(stream)) == stream


def test_sync_pattern_constant() -> None:
    assert INAV_SYNC_PATTERN == "0101100000"
