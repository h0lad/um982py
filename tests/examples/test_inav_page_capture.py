from __future__ import annotations

from pathlib import Path

from examples.inav_page_capture import (
    render_audit,
    render_campaign,
    render_page,
    render_word,
)
from examples.inav_page_capture.__main__ import _report

from um982py.experimental import (
    InavCampaign,
    InavSnapshot,
    InavWord,
    PageWindowAudit,
    WordTiming,
    extract_inav_pages,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

TRACKING_BASE = 0x3C2C00
PAGE_STATE_BASE = 0x3E5B00


def _snapshot() -> InavSnapshot:
    regions = {
        "tracking": (
            TRACKING_BASE,
            (FIXTURES / "inav-tracking-records.mem").read_bytes(),
        ),
        "page_states": (
            PAGE_STATE_BASE,
            (FIXTURES / "inav-page-states.mem").read_bytes(),
        ),
    }
    return InavSnapshot.from_regions(regions, application_restored=True)


def test_report_lists_pages_and_osnma_counts() -> None:
    report = _report(_snapshot())
    assert report["pages"] == 10
    assert report["pages_with_osnma"] == 3
    assert report["odd_pages"] == 6
    assert sorted(report["prns"]) == [6, 7, 11, 12, 14, 15, 16, 20, 29, 36]
    assert report["application_restored"] is True
    assert "OSNMA" in str(report["interpretation"])


def test_report_details_carry_the_decoded_part_fields() -> None:
    report = _report(_snapshot())
    details = {detail["prn"]: detail for detail in report["details"]}
    assert details[11]["osnma"] == "440b8924a2"
    assert details[29]["word_type"] == 1
    assert details[11]["even"] is False
    assert details[29]["even"] is True


def test_extracted_snapshot_matches_direct_extraction() -> None:
    snapshot = _snapshot()
    regions = {
        "tracking": (TRACKING_BASE, snapshot.regions["tracking"]),
        "page_states": (PAGE_STATE_BASE, snapshot.regions["page_states"]),
    }
    assert snapshot.pages == extract_inav_pages(regions)


def _campaign() -> InavCampaign:
    return InavCampaign((_snapshot(),))


def test_render_page_row_shows_part_word_and_osnma() -> None:
    pages = {page.prn: page for page in _campaign().pages}
    row = render_page(pages[11])
    assert " 11  " in row
    assert "odd/nom" in row
    assert "96c71102e24928a55246905500c0ebed" in row
    assert "440b8924a2" in row
    assert "yes" in row


def test_render_page_row_marks_alert_and_invalid() -> None:
    pages = {page.prn: page for page in _campaign().pages}
    assert "odd/alert" in render_page(pages[36])
    assert "  no " in render_page(pages[15])


def test_render_campaign_renders_all_sections() -> None:
    text = render_campaign(_campaign())
    assert "Galileo I/NAV page capture" in text
    assert "Snapshots:             1" in text
    assert "Pages:                 10 (10 unique)" in text
    assert "6, 7, 11, 12, 14, 15, 16, 20, 29, 36" in text
    assert "Application restored:  yes" in text
    assert "Captured page parts" in text
    assert "PRN    Ch  Part        Word  Valid" in text
    assert "OSNMA activity" in text
    assert "Checksum-verified words\n----------------------\n-" in text
    assert "Window decode audits" in text
    assert text.count("-") >= 2


def test_render_campaign_activity_carries_header_interpretation() -> None:
    text = render_campaign(_campaign())
    assert " 11 " in text
    assert "test/0/end_of_chain" in text
    assert "Observed" in text
    assert "yes" in text


def test_render_word_row_shows_fields_and_timing() -> None:
    word = InavWord(
        word_type=4,
        content=bytes(16),
        iod_nav=58,
        svid=2,
        timing=None,
    )
    row = render_word(word)
    assert row == "   4      58     2       -  -"
    timed = InavWord(
        word_type=5,
        content=bytes(16),
        iod_nav=None,
        svid=None,
        timing=WordTiming(week_number=1248, time_of_week=345655),
    )
    assert render_word(timed) == "   5       -     -    1248  345655"


def test_render_audit_row_and_empty_section() -> None:
    audit = PageWindowAudit(
        prn=12,
        sync_offset=49,
        viterbi_errors=33,
        tail_valid=False,
        ssp=None,
        decoded=bytes.fromhex("130225b0d8d602c7b602e443db9340"),
    )
    row = render_audit(audit)
    assert row == (
        " 12    49      33  no        -  130225b0d8d602c7b602e443db9340"
    )
    text = render_campaign(_campaign(), audits=[audit])
    assert "Window decode audits" in text
    assert row in text
    empty = render_campaign(_campaign(), audits=[])
    assert "Window decode audits" in empty
    assert "Decoded\n-" in empty
