from pathlib import Path

from um982py.experimental import (
    NmaStatus,
    PublicKeyStatus,
    assemble_osnma_subframe,
    decode_inav_page_part,
    extract_inav_pages,
    parse_nma_header,
)

FIXTURES = Path(__file__).parent / "fixtures"

TRACKING_BASE = 0x3C2C00
PAGE_STATE_BASE = 0x3E5B00

PAGES = {
    7: "96c71102e24928a55246905500c0ebed",
    8: "a0c71102f1c9bb36d68906270000516f",
    25: "01dd1102c909766e94c0f1ac00c06e3a",
}


def _regions() -> dict[str, tuple[int, bytes]]:
    tracking = (FIXTURES / "inav-tracking-records.mem").read_bytes()
    states = (FIXTURES / "inav-page-states.mem").read_bytes()
    return {
        "tracking": (TRACKING_BASE, tracking),
        "page_states": (PAGE_STATE_BASE, states),
    }


def test_extracts_the_tracked_galileo_pages() -> None:
    pages = extract_inav_pages(_regions())
    prns = sorted({page.prn for page in pages})
    assert prns == [2, 3, 7, 8, 10, 11, 12, 16, 25, 32]
    by_prn = {page.prn: page for page in pages}
    assert by_prn[7].page.hex() == PAGES[7]
    assert by_prn[8].page.hex() == PAGES[8]
    assert by_prn[25].page.hex() == PAGES[25]


def test_extracted_pages_share_one_time_counter() -> None:
    pages = extract_inav_pages(_regions())
    assert {page.time_counter for page in pages} == {577052}
    assert sum(page.page_valid for page in pages) == 8


def test_odd_nominal_part_carries_the_osnma_field() -> None:
    part = decode_inav_page_part(bytes.fromhex(PAGES[7]))
    assert not part.even
    assert part.page_type == 0
    assert part.osnma is not None
    assert part.osnma.hex() == "440b8924a2"
    assert part.hkroot_portion == b"\x44"
    assert part.mack_portion == b"\x0b\x89\x24\xa2"
    assert part.crc == b"\x41\x54\x03"
    assert part.ssp == 3


def test_even_nominal_part_opens_a_navigation_word() -> None:
    part = decode_inav_page_part(bytes.fromhex(PAGES[25]))
    assert part.even
    assert part.page_type == 0
    assert part.word_type == 1
    assert part.osnma is None


def test_extracted_pages_decode_consistently() -> None:
    pages = extract_inav_pages(_regions())
    parts = {page.prn: page.part for page in pages}
    assert parts[7].osnma is not None
    assert parts[25].word_type == 1


def test_nma_header_portion_decodes_test_values() -> None:
    header = parse_nma_header(b"\x44")
    assert header.status == NmaStatus.TEST
    assert header.chain_id == 0
    assert header.public_key_status == PublicKeyStatus.END_OF_CHAIN
    assert header.reserved == 0


def test_assemble_osnma_subframe_recombines_portions() -> None:
    part = decode_inav_page_part(bytes.fromhex(PAGES[7]))
    assert part.osnma is not None
    subframe = assemble_osnma_subframe(part.osnma * 15)
    assert len(subframe.hkroot) == 15
    assert len(subframe.mack) == 60
    assert subframe.hkroot == b"\x44" * 15
    assert subframe.header.status == NmaStatus.TEST


def test_assemble_osnma_subframe_requires_fifteen_fields() -> None:
    import pytest

    with pytest.raises(ValueError, match="Fifteen"):
        assemble_osnma_subframe(bytes(5 * 14))


def test_decode_rejects_empty_page() -> None:
    import pytest

    with pytest.raises(ValueError, match="empty"):
        decode_inav_page_part(b"")
