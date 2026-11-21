from __future__ import annotations

from pathlib import Path

from examples.inav_page_capture.__main__ import _report

from um982py.experimental import InavSnapshot, extract_inav_pages

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
