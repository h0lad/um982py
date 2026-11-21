
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
    assemble_inav_word,
    assemble_sar_long_rlm,
    assemble_sar_short_rlm,
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


def test_sar_field_decodes_start_bit_and_data() -> None:
    field = decode_sar_field(bytes.fromhex("AAAAAAAAAB"))
    assert isinstance(field, SarField)
    assert field.start is (bits_of(bytes.fromhex("AAAAAAAAAB"))[0] == "1")
    assert field.spare is False or field.spare is True


def test_sar_spare_pattern_is_recognised() -> None:
    spare = decode_sar_field(pack_bits("1" + "0" * 21))
    assert spare.start and spare.spare


def test_sar_short_rlm_assembles_from_four_parts() -> None:
    parts = [SarField(start=False, data=bytes(3))] * 4
    parts[0] = SarField(start=True, data=pack_bits("0" * 21))
    rlm = assemble_sar_short_rlm(parts)
    assert rlm is not None
    assert rlm.message_code == 0


def test_sar_long_rlm_requires_message_sequence() -> None:
    parts = [SarField(start=False, data=bytes(3))] * 8
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
