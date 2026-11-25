"""Tests for Galileo HAS message recovery against the ICD Annex C example."""

from has_annexc import (
    ANNEX_C_MESSAGE_HEX,
    ANNEX_C_PADDING_BITS,
    ANNEX_C_PAGES_HEX,
    ANNEX_C_PIDS,
    ANNEX_C_SUB_MATRIX_HEX,
    GENERATOR_POLYNOMIAL,
)
from um982py.experimental import (
    GALILEO_SIGNALS,
    GPS_SIGNALS,
    HasMessage,
    collect_has_page_sets,
    has_message,
    parse_mt1_message,
    validity_interval_s,
)
from um982py.experimental.inav_coding import GF_EXP, gf_multiply
from um982py.experimental.native_nav import GalileoHasPage


def annex_c_pages(prn: int = 1) -> list[GalileoHasPage]:
    """The Annex C pages as receiver pages of message 1/15/15."""
    header = bytes((0b00000101, 0b11101110))
    return [
        GalileoHasPage(
            prn=prn,
            channel=0,
            receiver_time_counter=0,
            data=header + bytes((pid,)) + bytes.fromhex(page_hex),
        )
        for pid, page_hex in ANNEX_C_PAGES_HEX
    ]


def annex_c_message() -> HasMessage:
    """The recovered Annex C message."""
    sets = collect_has_page_sets(annex_c_pages())
    assert len(sets) == 1
    message = sets[0].decode()
    assert message is not None
    return message


def test_field_powers_match_the_icd_table_41() -> None:
    sampled = {
        8: 29,
        9: 58,
        10: 116,
        11: 232,
        12: 205,
        13: 135,
        14: 19,
        239: 22,
        240: 44,
        241: 88,
        242: 176,
        243: 125,
        244: 250,
        245: 233,
        246: 207,
        247: 131,
        248: 27,
        249: 54,
        250: 108,
        251: 216,
        252: 173,
        253: 71,
        254: 142,
    }
    for power, octet in sampled.items():
        assert GF_EXP[power] == octet


def test_generator_polynomial_matches_the_published_roots() -> None:
    product = [1]
    for power in range(1, 224):
        root = GF_EXP[power]
        scaled = [0] * (len(product) + 1)
        for index, coefficient in enumerate(product):
            scaled[index + 1] ^= coefficient
            scaled[index] ^= gf_multiply(coefficient, root)
        product = scaled
    assert product == [*GENERATOR_POLYNOMIAL, 1]


def test_generator_rows_match_the_published_sub_matrix() -> None:
    residues = has_message._residues(15)
    rows = [has_message._codeword_row(pid, residues) for pid in ANNEX_C_PIDS]
    assert bytes(value for row in rows for value in row) == bytes.fromhex(
        ANNEX_C_SUB_MATRIX_HEX
    )


def test_annex_c_message_recovers_byte_exact() -> None:
    message = annex_c_message()
    assert message.octets == bytes.fromhex(ANNEX_C_MESSAGE_HEX)
    assert message.message_size == 15
    assert message.padding_bits == ANNEX_C_PADDING_BITS
    assert len(message.content_bits) == 6081
    assert message.consistent


def test_annex_c_mt1_blocks_parse_completely() -> None:
    message = annex_c_message()
    assert message.mt1 is not None
    mt1 = message.mt1
    assert mt1.complete
    assert mt1.unsupported is None
    assert mt1.consumed_bits == 6049
    header = mt1.header
    assert (header.toh_s, header.mask_id, header.iod_set_id) == (0, 0, 11)
    assert (
        header.mask_flag,
        header.orbit_corr_flag,
        header.clock_full_flag,
        header.clock_subset_flag,
        header.code_bias_flag,
        header.phase_bias_flag,
    ) == (True, True, False, False, True, True)
    assert mt1.mask is not None
    gps, galileo = mt1.mask.systems
    assert (gps.gnss_id, len(gps.satellites), gps.signals) == (0, 31, (0, 7))
    assert 11 not in gps.satellites
    assert gps.cell_mask_available and len(gps.cells) == 54
    assert (galileo.gnss_id, len(galileo.satellites), galileo.signals) == (
        2,
        22,
        (1, 4, 7, 13),
    )
    assert not galileo.cell_mask_available and len(galileo.cells) == 88
    assert mt1.orbits is not None
    assert mt1.orbit_validity_index == 10
    assert validity_interval_s(mt1.orbit_validity_index) == 300
    first = mt1.orbits[0]
    assert (first.satellite, first.iod_ref) == (1, 96)
    assert first.delta_radial_m is not None
    assert abs(first.delta_radial_m - 0.05) < 1e-12
    assert first.delta_in_track_m is not None
    assert abs(first.delta_in_track_m - 0.416) < 1e-12
    assert first.delta_cross_track_m is not None
    assert abs(first.delta_cross_track_m - 0.296) < 1e-12
    assert mt1.code_biases is not None and len(mt1.code_biases) == 142
    assert mt1.code_bias_validity_index == 14
    assert mt1.phase_biases is not None and len(mt1.phase_biases) == 142
    assert mt1.phase_bias_validity_index == 5
    assert all(bias.discontinuity_indicator == 0 for bias in mt1.phase_biases)
    assert mt1.phase_biases[0].bias_cycles is None
    assert mt1.clocks is None and mt1.clock_multipliers is None


def test_collector_groups_identities_and_keeps_the_latest_page() -> None:
    first = annex_c_pages(prn=2)[0]
    repeated = GalileoHasPage(
        prn=33,
        channel=1,
        receiver_time_counter=99,
        data=first.data[:3] + bytes(53),
    )
    other = GalileoHasPage(
        prn=2,
        channel=2,
        receiver_time_counter=1,
        data=bytes((0b00000110, 14, 3)) + bytes(53),
    )
    sets = collect_has_page_sets([first, repeated, other])
    assert [(s.message_type, s.message_id, s.message_size) for s in sets] == [
        (1, 15, 15),
        (1, 16, 15),
    ]
    page_set = sets[0]
    assert first.page_id is not None
    assert page_set.pages[first.page_id] == bytes(53)
    assert page_set.prns[first.page_id] == 33


def test_dummy_pages_are_ignored() -> None:
    dummy = GalileoHasPage(
        prn=19,
        channel=1,
        receiver_time_counter=0,
        data=bytes.fromhex("af3bc3") + bytes(53),
    )
    assert collect_has_page_sets([dummy]) == ()


def test_fewer_pages_than_the_size_do_not_decode() -> None:
    page_set = collect_has_page_sets(annex_c_pages()[:14])[0]
    assert not page_set.complete
    assert page_set.decode() is None


def test_pages_from_mixed_instances_are_flagged() -> None:
    extra = GalileoHasPage(
        prn=5,
        channel=9,
        receiver_time_counter=7,
        data=bytes((0b00000101, 0b11101110, 254)) + bytes(range(53)),
    )
    page_set = collect_has_page_sets([*annex_c_pages(), extra])[0]
    message = page_set.decode()
    assert message is not None
    assert message.octets == bytes.fromhex(ANNEX_C_MESSAGE_HEX)
    assert not message.consistent


def test_non_mt1_messages_skip_mt1_parsing() -> None:
    page = annex_c_pages()[0]
    other_type = GalileoHasPage(
        prn=1,
        channel=0,
        receiver_time_counter=0,
        data=bytes((0b00001011, 0, 1)) + page.encoded_page,
    )
    page_set = collect_has_page_sets([other_type])[0]
    message = page_set.decode()
    assert message is not None
    assert message.mt1 is None
    assert message.octets == page.encoded_page


def test_truncated_content_does_not_raise() -> None:
    result = parse_mt1_message("010")
    assert not result.complete
    assert result.unsupported == "truncated header"


def test_clock_subset_blocks_report_the_limit() -> None:
    bits = (
        "000000000000"  # time of hour
        "100100"  # mask, orbit, clock full, subset, code, phase
        "0000"  # reserved
        "00000"
        "00000"  # mask id, IOD set id
        "0001"
        "0000"  # one GNSS, GPS
        + "1"
        + "0" * 39  # one satellite
        + "1"
        + "0" * 15  # one signal
        + "0"  # cell mask not available
        + "000"  # navigation message index
        + "000000"  # reserved
    )
    result = parse_mt1_message(bits)
    assert result.unsupported == "clock subset block"
    assert not result.complete
    assert result.mask is not None and len(result.mask.systems) == 1


def test_validity_interval_table() -> None:
    assert validity_interval_s(0) == 5
    assert validity_interval_s(10) == 300
    assert validity_interval_s(14) == 3600
    assert validity_interval_s(15) is None


def test_singular_sub_matrices_do_not_decode() -> None:
    assert has_message._invert(((0, 0), (0, 0))) is None


def test_signal_name_tables_match_the_icd() -> None:
    assert GALILEO_SIGNALS[12] == "E6-B C/NAV"
    assert GALILEO_SIGNALS[3] == "E5a-I F/NAV"
    assert GPS_SIGNALS[0] == "L1 C/A"
    assert GPS_SIGNALS[6] == "L2 CM"
