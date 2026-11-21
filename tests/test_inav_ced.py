"""Clock and ephemeris decoding and recovery from the Galileo stream fixture."""

from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from um982py.experimental import (
    InavWord,
    RedCed,
    assemble_inav_word,
    decode_redced,
    read_inav_stream_csv,
    recover_fec2_ced,
    replay_inav_ced,
)

FIXTURE = Path(__file__).parent / "fixtures" / "inav-stream-six-satellites.csv"


@pytest.fixture(scope="module")
def parts() -> tuple[bytes, ...]:
    return read_inav_stream_csv(FIXTURE)[2]


@pytest.fixture(scope="module")
def words(parts: tuple[bytes, ...]) -> dict[int, InavWord]:
    # E02 broadcasts all four parity words across these two sub-frames.
    return {
        word.word_type: word
        for index in range(0, 60, 2)
        if (word := assemble_inav_word(parts[index], parts[index + 1])) is not None
    }


def test_redced_signed_scaling(parts: tuple[bytes, ...]) -> None:
    word = assemble_inav_word(parts[14], parts[15])
    assert word is not None
    assert word.content.hex() == "40c2e7eee7460b3662e46190b003a700"
    assert decode_redced(word) == RedCed(
        delta_a_m=6 * 2**8,
        eccentricity_x=743 * 2**-22,
        eccentricity_y=-548 * 2**-22,
        delta_i_semicircles=-11902 * 2**-22,
        omega0_semicircles=-1651620 * 2**-22,
        lambda0_semicircles=-3794677 * 2**-22,
        af0_s=3740 * 2**-26,
        af1_s_per_s=0,
    )


def test_fec2_any_four_words_with_parity_recover_original_words(
    words: dict[int, InavWord],
) -> None:
    data_types = (1, 2, 3, 4)
    original = tuple(words[kind].content for kind in data_types)
    for received in combinations((1, 2, 3, 4, 17, 18, 19, 20), 4):
        if received == data_types:
            continue
        recovered = recover_fec2_ced({kind: words[kind] for kind in received})
        assert recovered is not None, received
        assert recovered.iod_nav == 76
        assert recovered.words == original, received
        assert recovered.recovered_types == tuple(
            kind for kind in data_types if kind not in received
        )


def test_fec2_rejects_too_few_symbols_and_inconsistent_blocks(
    words: dict[int, InavWord],
) -> None:
    assert recover_fec2_ced({kind: words[kind] for kind in (1, 17, 19)}) is None

    parity = words[17]
    bad_parity = replace(
        parity, content=parity.content[:-1] + bytes([parity.content[-1] ^ 1])
    )
    assert recover_fec2_ced({**words, 17: bad_parity}) is None

    original = words[2]
    different_issue = replace(
        original,
        content=bytes((original.content[0], original.content[1] ^ 4))
        + original.content[2:],
    )
    assert recover_fec2_ced({**words, 2: different_issue}) is None


def test_ced_replay_recovers_missing_pages_at_the_right_gst(
    parts: tuple[bytes, ...],
    words: dict[int, InavWord],
) -> None:
    replay = replay_inav_ced((b"",) * 4 + parts[4:30])
    reduced = replay["redced"]
    assert isinstance(reduced, list)
    assert len(reduced) == 2
    assert reduced[0]["reference_time"] == {
        "week_number": 1251,
        "time_of_week": 277201,
    }
    fec2 = replay["fec2"]
    assert isinstance(fec2, list)
    assert len(fec2) == 1
    assert fec2[0]["subframe_time"] == {"week_number": 1251, "time_of_week": 277200}
    assert fec2[0]["recovered_types"] == (2, 4)
    assert fec2[0]["words"] == [words[kind].content.hex() for kind in (1, 2, 3, 4)]
